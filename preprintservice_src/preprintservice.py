#!/usr/bin/env python3
import os
import sys
import urllib3
import requests
import logging
import argparse
import subprocess as sp

from flask import Flask, flash, request, redirect, url_for, Response, render_template, send_from_directory, make_response, jsonify
from flask_swagger_ui import get_swaggerui_blueprint
from werkzeug.utils import secure_filename
from werkzeug.exceptions import abort, RequestEntityTooLarge


# If the file size is over 100MB, tweaking would lack due to performance issues.
# MAX_CONTENT_LENGTH = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {'stl', '3mf', 'obj'}
LOCAL_SLIC3R_PATH = "/home/cschranz/software/Slic3r/slic3r-dist/bin/prusa-slicer"
SWAGGER_URL = '/api'
API_URL = '/static/swagger.yaml'  # the main directory of the app

# set loglevel to info
logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

# create the Flask app
app = Flask(__name__)
# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Register the Swagger ui as blueprint
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,  # Swagger UI static files will be mapped
    API_URL,
    config={  # Swagger UI config overrides
        'app_name': "API of the PrePrintService"
    })
app.register_blueprint(swaggerui_blueprint)

# set current path or use /src/, as docker use that path but doesn't know __file__
CURPATH = os.path.dirname(os.path.abspath(__file__)) + os.sep  # TODO clear this
if len(CURPATH) <= 2:
	app.logger.error("__file__ too short, setting curpath to /src/.")
	CURPATH = "/src/"

# app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['UPLOAD_FOLDER'] = os.path.join(CURPATH, "uploads")
app.config['PROFILE_FOLDER'] = os.path.join(CURPATH, "profiles")
app.config['DEFAULT_PROFILE'] = os.path.join(app.config['PROFILE_FOLDER'], "profile_015mm_none.ini")

# search and select the appropriate slic3r path
for path in  ["/Slic3r/slic3r-dist/bin/prusa-slicer", LOCAL_SLIC3R_PATH]:
	if os.path.isfile(path):
		app.config['SLIC3R_PATH'] = path
		app.logger.info(f"Slic3r was loaded from '{path}'")
		break
if 'SLIC3R_PATH' not in app.config:
	app.logger.warning("The Slic3r can't be found, make sure it is available in one of these paths:")
	app.logger.warning(f'["/Slic3r/slic3r-dist/bin/prusa-slicer", {LOCAL_SLIC3R_PATH}]')
	app.logger.warning("The slicing functionality can't be used.")


def allowed_file(filename):
	"""Return if the filename has an allowed extension."""
	return '.' in filename and filename.split('.')[-1].lower() in ALLOWED_EXTENSIONS


@app.route("/", methods=['GET', 'POST'])
@app.route("/tweak", methods=['GET', 'POST'])
@app.route("/tweak/", methods=['GET', 'POST'])
def tweak_slice_file():
	"""Routine for Auto-Orientation and Slicing the object."""
	# try:
	if request.method == 'POST':
		app.logger.debug("request on: %s", request)
		# available keys in request.forms: 'machinecode_name', 'tweak_option', 'request_source' 'octoprint_url', 'apikey'
		
		# 0) Get url on which to upload the requested file
		if request.form.get("octoprint_url") is not None:
			app.logger.info(f'Getting request from octoprint server: {request.form.get("octoprint_url")}')
		else:
			app.logger.info("Getting request from user interface")
		app.logger.info(f"Request with payload: {dict(request.form).items()}")

		# 1) Check if the input is correct
		# 1.1) Get the model file and check for correctness
		if 'model' not in request.files:
			return jsonify('No model file in request')
		# load the file
		uploaded_file = request.files['model']
		# if no file was selected, submit an empty one
		if uploaded_file.filename == '':
			flash('No selected model', 'warning')
			return redirect(request.url)
		if not (uploaded_file and allowed_file(uploaded_file.filename)):
			flash('Invalid model extension', 'warning')
			return redirect(request.url)
		filename = secure_filename(uploaded_file.filename)
		filename_extension = "." + filename.split(".")[-1]
		app.logger.info(f"Uploaded new model: {filename}")
		uploaded_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
		app.logger.info(f"Saved model to '{os.path.join(app.config['UPLOAD_FOLDER'], filename)}'")

		# 1.2) Get the profile
		if 'profile' in request.files:
			# in webUI, there is always this option available, no slicing is called 'no_slicing'
			profile = request.files["profile"]
			if profile.filename == '':
				flash('No selected profile', 'warning')
				return redirect(request.url)
			elif profile == "no_slicing":
				profile_path = None
			else:
				profilename = secure_filename(profile.filename)
				app.logger.info("Uploaded new profile: {}".format(profilename))
				profile.save(os.path.join(app.config['PROFILE_FOLDER'], profilename))
				profile_path = os.path.join(app.config['PROFILE_FOLDER'], profilename)
		else:
			if request.form.get("profile"):
				profile = request.form.get("profile")
				if profile == "no_slicing":
					profile_path = None
				else:
					profile_path = os.path.join(app.config["PROFILE_FOLDER"], profile)
					if not os.path.exists(profile_path):
						profile_path = app.config['DEFAULT_PROFILE']
			else:
				profile_path = None
		app.logger.info("Using profile: '{}'".format(profile_path))

		# 1.3) Get the tweak actions
		# Get the tweak option and use extended_volume as default
                # of the form: "tweak_extended_volume_returntweaked")
		tweak_option = request.form.get("tweak_option", "tweak_extended_volume_returntweaked")  
		app.logger.info(f"Using Tweaker options: '{tweak_option}'")

		# 2.1) retrieve the model file and perform the tweaking
		if tweak_option.startswith("tweak_") and "_keep" not in tweak_option:
			tweaked_filename = filename.replace(filename_extension, f"_tweaked{filename_extension}")
			if request.form.get("request_source") == "octoprint":  # rename if requested from octoprint
				tweaked_filename = tweaked_filename.split(".tmp.")[0] + f"_tweaked{filename_extension}"
			tweak_cmd = f"{sys.executable} {os.path.join(CURPATH, 'Tweaker-3', 'Tweaker.py')}"
			tweak_cmd += f" -i {os.path.join(app.config['UPLOAD_FOLDER'], filename)}"
			# if "_keep" in tweak_option:  # convert to binary
			# 	tweak_cmd += " -c"
			if "extended_" in tweak_option:
				tweak_cmd += " --extended"
			if "_surface" in tweak_option:
				tweak_cmd += " --minimize surface"
			tweak_cmd += f" -o {os.path.join(app.config['UPLOAD_FOLDER'], tweaked_filename)}"
			app.logger.info("Running Tweaker with command: '{}'".format(tweak_cmd))

			# execute as subprocess and handle the response
			pipe = sp.Popen(tweak_cmd, shell=True, stdout=sp.PIPE, stderr=sp.PIPE)
			response = pipe.communicate()
			filename = tweaked_filename
			if pipe.returncode == 0 and len(response[0]) == 0:
				app.logger.info("Tweaking was successful")
			else:
				msg = f"Tweaking was executed with the returncode {pipe.returncode} and the warning:\n"
				msg += f"Response: {response[0]}, error: {response[1].decode('utf-8').strip()}"
				app.logger.error(msg)
				flash(msg, "error")
				return redirect(request.url)
		else:
			app.logger.info("Tweaking was skipped as expected.")

		# 2.2) Send back tweaked file to requester, currently not supported as we can't send back the STL in an extra API call
		if request.form.get("octoprint_url") and (tweak_option.endswith("_returntweaked") or profile_path is not None):
			app.logger.info("Sending back tweaked model file")
			# Upload the tweaked model via API to octoprint
			# find the apikey in octoprint server, settings, access control
			outfile = os.path.join(app.config['UPLOAD_FOLDER'], filename)
			app.logger.info("Sending file '{}' to URL '{}'".format(outfile, request.form.get("octoprint_url")))
			files = {'file': open(outfile, 'rb')}
			url_with_key = os.path.join(request.form.get("octoprint_url"), f'api/files/local?apikey={request.form.get("apikey")}')
			r = requests.post(url_with_key, files=files, verify=False)
			if r.status_code == 201:
				app.logger.info(f"Sended back tweaked stl to server {request.form.get('octoprint_url')} with code '{r.status_code}'")
				flash(f"Sended back tweaked stl to server {request.form.get('octoprint_url')} with code '{r.status_code}'", "success")
			else:
				app.logger.warning(f"Problem while loading tweaked stl to Octoprint server '{request.form.get('octoprint_url')}' with code '{r.status_code}'")
				# app.logger.warning(r.text)
				flash(f"Problem while loading tweaked stl back to server with code '{r.status_code}'")
		else:
			app.logger.info("Sending back file was skipped as expected.")

		# 3) Slice the tweaked model using Slic3r
		# 3.1) Get the machinecode_name, if slicing was chosen
		if profile_path:
			machinecode_name = request.form.get("machinecode_name", 
				filename.replace(filename_extension, "_withPPS.gcode"))
			# if not tweak_option.startswith("tweak_keep"):
			# 	machinecode_name = machinecode_name.replace(".gcode", "_tweaked.gcode")
			gcode_path = os.path.join(app.config["UPLOAD_FOLDER"], machinecode_name)
			app.logger.info(f"Machinecode will have the name '{machinecode_name}'")

		# 3.2) Slice the file if it is set, else set gcode_path to None
		if profile_path:
			slice_cmd = f"{app.config['SLIC3R_PATH']} --export-gcode --repair {os.path.join(app.config['UPLOAD_FOLDER'], filename)} "
			slice_cmd += f" --load {profile_path} --output {gcode_path}"
			app.logger.info(f"Slicing the model with the command: '{slice_cmd}'")
			
			# execute as subprocess and handle the response
			pipe = sp.Popen(slice_cmd, shell=True, stdout=sp.PIPE, stderr=sp.PIPE)
			response = pipe.communicate()
			if pipe.returncode == 0:
				app.logger.info("Slicing was successful")
			else:
				msg = f"Slicing was executed with a nonzero returncode: {pipe.returncode}.\n"
				msg += f"Response: {response[0]}, error message: {response[1].decode('utf-8').strip()}."
				if pipe.returncode in [126, 127] or "Exec format error" in response[1].decode('utf-8').strip():
					msg += "\nYour Slicer version can't be found. Make sure the provided path works in command line."
					msg += "\nSearch an appropriate version for your cpu architecture in https://github.com/prusa3d/PrusaSlicer/releases"
				app.logger.error(msg)
				flash(msg, "error")
				return redirect(request.url)
			
			if profile_path.split(os.sep)[-1].startswith("slicing-profile-temp") and profile_path.endswith(".profile"):
				os.remove(profile_path)
		else:
			gcode_path = None

		# 4) Redirect the ready gcode or tweaked model file from UI or direct API call
		if gcode_path:  # model was sliced, return gcode
			app.logger.debug("Handling the download of '{}'.".format(gcode_path))
			if request.headers.get('Accept') == "text/plain":
				response = Response(open(gcode_path, 'rb').read())
			else:
				response = Response(open(gcode_path, 'rb').read(), mimetype='application/octet-stream')
				response.headers['Content-Disposition'] = "inline; filename=" + machinecode_name
			response.headers['Access-Control-Allow-Origin'] = "*"
		else:  # model was not sliced, return tweaked model
			tweaked_file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
			app.logger.debug("Handling the download of '{}'.".format(tweaked_file_path))
			if request.headers.get('Accept') == "text/plain":
				response = Response(open(tweaked_file_path, 'rb').read())
			else:
				response = Response(open(tweaked_file_path, 'rb').read(), mimetype='application/octet-stream')
				response.headers['Content-Disposition'] = "inline; filename=" + filename
			response.headers['Access-Control-Allow-Origin'] = "*"
		return response
	else:
		return render_template('tweak_slice.html', profiles=os.listdir(app.config['PROFILE_FOLDER']))
	# except RequestEntityTooLarge:
	# 	abort(413)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, "templates"),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')
			       
@app.route("/connection")
def connection():
	return jsonify({"value": "ok"}), 200

@app.route("/about")
def about():
	return render_template("about.html")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Preprint Service for 3D printing, combinting Auto-orientation and Slicing.')
	parser.add_argument("-p", dest="port", help="port to listen on, default: 2304", default="2304")
	parser.add_argument("-l", dest="logfile", help="logfile, default: None", default=None)
	args = parser.parse_args()

	if args.logfile:
		fmt = "%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s"
		level = logging.DEBUG
		logging.basicConfig(format=fmt, filename=args.logfile, level=level)

	app.secret_key = '3Dprint4life'
	# app.config['SESSION_TYPE'] = 'filesystem'
	app.run(host="0.0.0.0", port=int(args.port), debug=True)
