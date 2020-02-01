#!/usr/bin/env python3
import os
import requests
import urllib3
from flask import Flask, flash, request, redirect, url_for, Response, render_template, make_response, jsonify
from werkzeug.utils import secure_filename
from werkzeug.exceptions import abort, RequestEntityTooLarge

import logging
import argparse


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# If the file size is over 100MB, tweaking would lack due to performance issues.
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {'stl', '3mf', 'obj'}

# set current path or use /src/, as docker use that path but doesn't know __file__
CURPATH = os.path.dirname(os.path.abspath(__file__)) + os.sep
if len(CURPATH) <= 2:
	app.logger.error("__file__ too short, setting curpath hard.")
	CURPATH = "/src/"

app.config['UPLOAD_FOLDER'] = os.path.join(CURPATH, "uploads")
app.config['PROFILE_FOLDER'] = os.path.join(CURPATH, "profiles")
app.config['DEFAULT_PROFILE'] = os.path.join(app.config['PROFILE_FOLDER'], "profile_015mm_none.ini")
app.config['SLIC3R_PATHS'] = ["/Slic3r/slic3r-dist/slic3r", "/home/chris/Documents/software/Slic3r/Slic3rPE-1.41.2+linux64-full-201811221508/slic3r"]
for path in app.config['SLIC3R_PATHS']:
	if os.path.isfile(path):
		app.config['SLIC3R_PATH'] = path
		break


def allowed_file(filename):
	return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/", methods=['GET', 'POST'])
@app.route("/tweak", methods=['GET', 'POST'])
def tweak_slice_file():
	try:
		if request.method == 'POST':
			app.logger.debug("request on: %s", request)
			# 0) Get url on which to upload the requested file
			octoprint_url = request.form.get("octoprint_url", None)
			if octoprint_url:
				app.logger.info("Getting request from octoprint server: {}".format(octoprint_url.split("?apikey")[0]))
			else:
				app.logger.info("Getting request")

			# 1) Check if the input is correct
			# 1.1) Get the model file and check for correctness
			if 'model' not in request.files:
				return jsonify('No model file in request')
			# manage the file
			uploaded_file = request.files['model']
			# if no file was selected, submit an empty one
			if uploaded_file.filename == '':
				flash('No selected model')
				return redirect(request.url)
			if not (uploaded_file and allowed_file(uploaded_file.filename)):
				flash('Invalid model')
				return redirect(request.url)
			filename = secure_filename(uploaded_file.filename)
			app.logger.info("Uploaded new model: {}".format(filename))
			uploaded_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
			app.logger.info("Saved model to {}/{}".format(app.config['UPLOAD_FOLDER'], filename))

			# 1.2) Get the profile
			if 'profile' in request.files:
				profile = request.files["profile"]
				if profile.filename == '':
					flash('No selected profile')
					return redirect(request.url)
				elif profile == "no_slicing":
					profile_path = None
				else:
					profilename = secure_filename(profile.filename)
					app.logger.info("Uploaded new profile: {}".format(profilename))
					profile.save(os.path.join(app.config['PROFILE_FOLDER'], profilename))
					profile_path = os.path.join(app.config['PROFILE_FOLDER'], profilename)
			else:
				profile = request.form.get("profile")
				if profile == "no_slicing":
					profile_path = None
				else:
					flash('No profile in request, using default profile')
					profile_path = os.path.join(app.config["PROFILE_FOLDER"], profile)
					if not os.path.exists(profile_path):
						profile_path = app.config['DEFAULT_PROFILE']
			app.logger.info("Using profile: {}".format(profile_path))

			# 1.3) Get the tweak actions
			# Get the tweak option and use extendedTweak minimize the volume as default
			tweak_actions = request.form.get("tweak_actions")  # of the form: "tweak slice get_tweaked_stl")
			command = "Convert"
			if not tweak_actions:  # This is the case in the UI mode
				tweak_actions = list()
				if profile_path:
					tweak_actions.append("slice")
				command = request.form.get("tweak_option", "Convert")
				if command and command != "Convert":
					tweak_actions.append("tweak")
			else:
				tweak_actions = tweak_actions.split()
			if "tweak" in tweak_actions:
				command = "extendedTweakVol"
			app.logger.info("Using Tweaker actions: {}".format(", ".join(tweak_actions)))
			cmd_map = dict({"Tweak": "",
							"extendedTweak": "-x",
							"extendedTweakVol": "-x -vol",
							"Convert": "-c",
							"ascii STL": "-t asciistl",
							"binary STL": "-t binarystl"})

			# 1.4) Get the machinecode_name, if slicing was chosen
			if profile_path:
				machinecode_name = request.form.get("machinecode_name", filename.replace(".stl", ".gcode"))
				# if "tweak" in tweak_actions:
				# 	machinecode_name = "tweaked_{}".format(machinecode_name)
				gcode_path = os.path.join(app.config["UPLOAD_FOLDER"], machinecode_name)
				app.logger.info("Machinecode will have name {}".format(machinecode_name))

			# 2.1) retrieve the model file and perform the tweaking
			if "tweak" in tweak_actions:
				cmd = "python3 {curpath}Tweaker-3{sep}Tweaker.py -i {upload_folder}{sep}{input} {cmd} " \
					  "{output} -o {upload_folder}{sep}tweaked_{input}".format(
					curpath=CURPATH, sep=os.sep, upload_folder=app.config['UPLOAD_FOLDER'], input=filename,
					cmd=cmd_map[command], output=cmd_map["binary STL"])

				app.logger.info("Running Tweak with command: '{}'".format(cmd))
				ret = os.popen(cmd)
				response = ret.read()
				if response == "":
					app.logger.info("Tweaking was successful")
				else:
					app.logger.error("Tweaking was executed with the warning: {}.".format(response))
				filename = "tweaked_{}".format(filename)
			else:
				app.logger.info("Tweaking was skipped as expected.")

			# 2.2) Send back tweaked file to requester
			if octoprint_url and ("get_tweaked_stl" in tweak_actions or "slice" not in tweak_actions):
				# Upload the tweaked model via API to octoprint
				# find the apikey in octoprint server, settings, access control
				outfile = "{UPLOAD_FOLDER}{sep}{filename}".format(UPLOAD_FOLDER=app.config['UPLOAD_FOLDER'],
																  filename=filename, sep=os.sep)
				app.logger.info("Sending file '{}' to URL '{}'".format(outfile, octoprint_url.split("?apikey")[0]))
				files = {'file': open(outfile, 'rb')}
				r = requests.post(octoprint_url, files=files, verify=False)
				if r.status_code == 201:
					app.logger.info("Sended back tweaked stl to server {} with code '{}'".
									format(octoprint_url.split("?apikey")[0], r.status_code))
					flash("Sended back tweaked stl to server {} with code '{}'".format(
						octoprint_url.split("?apikey")[0], r.status_code))
				else:
					app.logger.warning("Problem while loading tweaked stl to Octoprint server {} with code '{}'"
									   .format(octoprint_url.split("?apikey")[0], r.status_code))
					# app.logger.warning(r.text)
					flash("Problem while loading tweaked stl back to server with code '{}'".format(r.status_code))
			else:
				app.logger.info("Sending back file was skipped as expected.")

			# 3) Slice the tweaked model using Slic3r
			# Slice the file if it is set, else set gcode_path to None
			if profile_path and "slice" in tweak_actions:
				cmd = "{SLIC3R_PATH} {UPLOAD_FOLDER}{sep}{filename} --load {profile} -o {gcode_path}".format(
					sep=os.sep, SLIC3R_PATH=app.config['SLIC3R_PATH'], UPLOAD_FOLDER=app.config['UPLOAD_FOLDER'],
					filename=filename, profile=profile_path, gcode_path=gcode_path)
				app.logger.info("Slicing the tweaked model with command: {}".format(cmd))
				# ret = os.popen(cmd)
				response = os.popen(cmd).read()
				if "Done. Process took" in response:
					app.logger.info("Slicing was successful")
				else:
					app.logger.error("Slicing was executed with the warning: {}.".format(response))
				if profile_path.split(os.sep)[-1].startswith("slicing-profile-temp") and profile_path.endswith(".profile"):
					os.remove(profile_path)
			else:
				gcode_path = None

			# 4) Redirect the ready gcode if a octoprint url was given
			if octoprint_url and gcode_path:
				# Upload a model via API to octoprint
				# find the apikey in octoprint server, settings, access control
				# outfile = "{gcode_path}".format(gcode_path=gcode_path)
				app.logger.info("Sending file '{}' to URL '{}'".format(gcode_path, octoprint_url.split("?apikey")[0]))
				files = {'file': open(gcode_path, 'rb')}
				r = requests.post(octoprint_url, files=files, verify=False)
				if r.status_code == 201:
					app.logger.info("Sended back tweaked stl to server {} with code '{}'".
									format(octoprint_url.split("?apikey")[0],  r.status_code))
					flash("Sended back tweaked stl to server {} with code '{}'".format(
						octoprint_url.split("?apikey")[0], r.status_code))
				else:
					app.logger.warning("Problem while loading file to Octoprint server {} with code '{}'".format(
						octoprint_url.split("?apikey")[0], r.status_code))
					# app.logger.warning(r.text)
					flash("Problem while loading file back to server with code '{}'".format(r.status_code))
				return redirect(octoprint_url)
			else:
				app.logger.debug("Handling the download of the binary data, either tweaked stl or gcode.")
				if gcode_path:  # model was sliced, return gcode
					if request.headers.get('Accept') == "text/plain":
						response = Response(open(gcode_path, 'rb').read())
					else:
						response = Response(open(gcode_path, 'rb').read(), mimetype='application/octet-stream')
						response.headers['Content-Disposition'] = "inline; filename=" + gcode_path
					response.headers['Access-Control-Allow-Origin'] = "*"
				else:  # model was not sliced, return tweaked model
					tweaked_file_path = "{upload_folder}{sep}{input}".format(
						sep=os.sep, upload_folder=app.config['UPLOAD_FOLDER'], input=filename)
					if request.headers.get('Accept') == "text/plain":
						response = Response(open(tweaked_file_path, 'rb').read())
					else:
						response = Response(open(tweaked_file_path, 'rb').read(), mimetype='application/octet-stream')
						response.headers['Content-Disposition'] = "inline; filename=" + filename
					response.headers['Access-Control-Allow-Origin'] = "*"

				return response

		else:
			return render_template('tweak_slice.html', profiles=os.listdir(app.config['PROFILE_FOLDER']))
	except RequestEntityTooLarge:
		abort(413)


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='STL Tweaking Service.')
	parser.add_argument("-p", dest="port", help="port to listen on default: 2304", default="2304")
	parser.add_argument("-l", dest="logfile", help="logfile, default: None", default=None)
	args = parser.parse_args()

	if args.logfile:
		fmt = "%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s"
		level = logging.DEBUG
		logging.basicConfig(format=fmt, filename=args.logfile, level=level)

	app.secret_key = 'secret_key'
	# app.config['SESSION_TYPE'] = 'filesystem'
	app.run(host="0.0.0.0", port=int(args.port), debug=True)
