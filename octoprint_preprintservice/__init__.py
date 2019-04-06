# coding=utf-8
from __future__ import absolute_import

import logging
import logging.handlers

import os
import re
import time
import json
import flask
import requests
import tempfile
from collections import defaultdict
from pkg_resources import parse_version

import octoprint.filemanager
import octoprint.filemanager.storage
import octoprint.plugin
from octoprint.util.paths import normalize as normalize_path

from .profile import Profile

blueprint = flask.Blueprint("plugin.preprintservice", __name__)

### (Don't forget to remove me)
# This is a basic skeleton for your plugin's __init__.py. You probably want to adjust the class name of your plugin
# as well as the plugin mixins it's subclassing from. This is really just a basic skeleton to get you started,
# defining your plugin as a template plugin, settings and asset plugin. Feel free to add or remove mixins
# as necessary.
#
# Take a look at the documentation on what other plugin mixins are available.


class PreprintservicePlugin(octoprint.plugin.SlicerPlugin,
							octoprint.plugin.StartupPlugin,
							octoprint.plugin.SettingsPlugin,
							octoprint.plugin.AssetPlugin,
							octoprint.plugin.BlueprintPlugin,
							octoprint.plugin.TemplatePlugin,
							octoprint.plugin.EventHandlerPlugin):
	def __init__(self):
		# setup job tracking across threads
		import threading
		self._slicing_commands = dict()
		self._slicing_commands_mutex = threading.Lock()
		self._cancelled_jobs = []
		self._cancelled_jobs_mutex = threading.Lock()
		self._job_mutex = threading.Lock()

	# ~~ StartupPlugin API
	def on_after_startup(self):
		self._logger.info("Hello from the PrePrintService plugin! (more: %s)" % self._settings.get(["url"]))
		print("\nDuplicate File, deletion\n")

	def get_settings_defaults(self):
		return dict(url="http://localhost:2304/",
					slic3r_engine=normalize_path("/usr/bin/slic3r"),
					default_profile=os.path.join(os.path.dirname(os.path.realpath(__file__)), "profiles", "default_slic3r_profile.ini"),
					debug_logging=True
					)

	# ~~ SettingsPlugin mixin

	def on_settings_save(self, data):
		self._logger.info("on_settings_save")
		old_debug_logging = self._settings.get_boolean(["debug_logging"])

		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		new_debug_logging = self._settings.get_boolean(["debug_logging"])
		if old_debug_logging != new_debug_logging:
			if new_debug_logging:
				self._logger.setLevel(logging.DEBUG)
			else:
				self._logger.setLevel(logging.CRITICAL)

	def get_template_vars(self):
		return dict(url=self._settings.get(["url"]))

	# ~~ AssetPlugin mixin

	def get_assets(self):
		# Define your plugin's asset files to automatically include in the
		# core UI here.
		return dict(
			js=["js/preprintservice.js"],
			css=["css/preprintservice.css"],
			less=["less/preprintservice.less"]
		)

	# ~~ Softwareupdate hook

	def get_update_information(self):
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here. See https://github.com/foosel/OctoPrint/wiki/Plugin:-Software-Update
		# for details.
		return dict(
			preprintservice=dict(
				displayName="Preprintservice Plugin",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="christophschranz",
				repo="OctoPrint-PrePrintService",
				current=self._plugin_version,

				# update method: pip
				pip="https://github.com/christophschranz/OctoPrint-PrePrintService/archive/{target_version}.zip"
			)
		)

	# ~~ BlueprintPlugin API

	@octoprint.plugin.BlueprintPlugin.route("/import", methods=["POST"])
	def importSlic3rProfile(self):
		import datetime
		import tempfile
		self._logger.info("importSlic3rProfile")

		input_name = "file"
		input_upload_name = input_name + "." + self._settings.global_get(["server", "uploads", "nameSuffix"])
		input_upload_path = input_name + "." + self._settings.global_get(["server", "uploads", "pathSuffix"])

		if input_upload_name in flask.request.values and input_upload_path in flask.request.values:
			filename = flask.request.values[input_upload_name]
			try:
				profile_dict, imported_name, imported_description = Profile.from_slic3r_ini(
					flask.request.values[input_upload_path])
			except Exception as e:
				return flask.make_response(
					"Something went wrong while converting imported profile: {message}".format(e.message), 500)

		elif input_name in flask.request.files:
			temp_file = tempfile.NamedTemporaryFile("wb", delete=False)
			try:
				temp_file.close()
				upload = flask.request.files[input_name]
				upload.save(temp_file.name)
				profile_dict, imported_name, imported_description = Profile.from_slic3r_ini(temp_file.name)
				# profile_dict, imported_name, imported_description = None, None, None
			except Exception as e:
				return flask.make_response(
					"Something went wrong while converting imported profile: {message}".format(e.message), 500)
			finally:
				os.remove(temp_file)

			filename = upload.filename

		else:
			return flask.make_response("No file included", 400)

		name, _ = os.path.splitext(filename)

		# default values for name, display name and description
		profile_name = _sanitize_name(name)
		profile_display_name = imported_name if imported_name is not None else name
		profile_description = imported_description if imported_description is not None else "Imported from {filename} on {date}".format(
			filename=filename, date=octoprint.util.get_formatted_datetime(datetime.datetime.now()))
		profile_allow_overwrite = False

		# overrides
		if "name" in flask.request.values:
			profile_name = flask.request.values["name"]
		if "displayName" in flask.request.values:
			profile_display_name = flask.request.values["displayName"]
		if "description" in flask.request.values:
			profile_description = flask.request.values["description"]
		if "allowOverwrite" in flask.request.values:
			from octoprint.server.api import valid_boolean_trues
			profile_allow_overwrite = flask.request.values["allowOverwrite"] in valid_boolean_trues

		self._slicing_manager.save_profile("preprintservice",  profile_name, profile_dict,
										   allow_overwrite=profile_allow_overwrite,
										   display_name=profile_display_name,
										   description=profile_description)

		result = dict(
			resource=flask.url_for("api.slicingGetSlicerProfile", slicer="preprintservice", name=profile_name,
								   external=False),
			displayName=profile_display_name,
			description=profile_description
		)
		r = flask.make_response(flask.jsonify(result), 201)
		r.headers["Location"] = result["resource"]
		return r

	# EventPlugin
	def on_event(self, event, payload):
		print("\nEVENT: {}: {}\n".format(event, payload))
		# Extract Gcode name and set it as instance var
		if event == "SlicingStarted":
			self.machinecode_name = payload.get("gcode", None)
		# if event == "FileAdded":
			# If the Added Name equals the self.machincode_name, delete it as it the empty duplicate
			# if payload.get("name", None) == self.machinecode_name:
			# 	print("\nDuplicate File, deletion\n")
				# octoprint.util.silent_remove(self.machinecode_name)
				# octoprint.util.silent_remove(".octoprint/uploads/{}".format(self.machinecode_name))

				# url = "http://localhost:5000/api/files/local/{}?apikey=A943AB47727A461F9CEF9ECD2E4E1E60".format(self.machinecode_name)
				# res = requests.delete(url)
				# if res.status_code == 204:
				# 	print("Successfully deleted file")
				# 	self.machinecode_name = None
				# else:
				# 	print("Coudn't delete file, status code: {}, text {}".format(res.status_code, res.text))

	# # API key validator
	# def hook(self, apikey, *args, **kwargs):
	# 	from octoprint.server import userManager
	# 	print("\n\nAPI key: {}".format(apikey))
	# 	return userManager.findUser(userid=apikey)

	# SlicerPlugin API
	def is_slicer_configured(self):
		slic3r_engine = normalize_path(self._settings.get(["slic3r_engine"]))
		return slic3r_engine is not None and os.path.exists(slic3r_engine)

	def get_slicer_properties(self):
		return dict(
			type="preprintservice",
			name="PrePrintService",
			same_device=False,
			progress_report=False)

	def get_slicer_default_profile(self):
		self._logger.info("get_slicer_default_profile")
		path = self._settings.get(["default_profile"])
		if not path:
			path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "profiles", "default_slic3r_profile.ini")
		return self.get_slicer_profile(path)

	def get_slicer_profile(self, path):
		profile_dict, display_name, description = self._load_profile(path)
		properties = self.get_slicer_properties()
		# self._logger.info("get_slicer_profile: {}".format(profile_dict))
		return octoprint.slicing.SlicingProfile(properties["type"], "unknown", profile_dict, display_name=display_name,
												description=description)

	def save_slicer_profile(self, path, profile, allow_overwrite=True, overrides=None):
		from octoprint.util import dict_merge
		if overrides is not None:
			new_profile = dict_merge(profile.data, overrides)
		else:
			new_profile = profile.data

		self._save_profile(path, new_profile, allow_overwrite=allow_overwrite, display_name=profile.display_name,
						   description=profile.description)

	def do_slice(self, model_path, printer_profile, machinecode_path=None, profile_path=None, position=None,
				 on_progress=None, on_progress_args=None, on_progress_kwargs=None, *args, **kwargs):
		# Get the default profile if none was set
		if not profile_path:
			profile_path = self._settings.get(["default_profile"])

		with self._job_mutex:
			print("\n\n")
			print(self._slicing_commands.items())
			print(open(machinecode_path).read())
			print(machinecode_path)
			# print(self.get_slicer_profile(profile_path))
			profile_dict, display_name, description = self._load_profile(profile_path)
			print("\n\n")

			# machinecode_path is a string based on a random tmpfile
			if self.machinecode_name:
				machinecode_path = self.machinecode_name
			else:
				path, _ = os.path.splitext(model_path)
				machinecode_path = path + "." + display_name.split("\n")[0] + ".gcode"
			print("\nMachinecode_name: {}\n".format(machinecode_path))

		if position and isinstance(position, dict) and "x" in position and "y" in position:
			posX = position["x"]
			posY = position["y"]
		elif printer_profile["volume"]["formFactor"] == "circular" or printer_profile["volume"]["origin"] == "center":
			posX = 0
			posY = 0
		else:
			posX = printer_profile["volume"]["width"] / 2.0
			posY = printer_profile["volume"]["depth"] / 2.0
		center = json.dumps(dict({"posX": posX, "posY": posY}))
		self._logger.info("Center of the model: {}".format(center))

		# Try connection to PrePrintService
		url = self._settings.get(["url"]) + 'upload-octoprint'
		try:
			r = requests.get(url)
			if r.status_code != 200:
				self._logger.info("Connection to {} cound not be established, status code {}"
								  .format(url, r.status_code))
				return False, "Connection to {} cound not be established.".format(url)
		except requests.ConnectionError:
			self._logger.info("Connection to {} cound not be established.".format(url))
			return False, "Connection to {} cound not be established.".format(url)


		# Sending model, profile and gcodename to PrePrintService
		files = {'model': open(model_path, 'rb'),
				 'profile': open(profile_path, 'rb')}  # profile path is wrong (tmp file), but model path is correct
		data = {"machinecode_name": os.path.split(machinecode_path)[-1],
				"center": center}
		self._logger.info("Sending file {} and profile {} with center to {} and get {}".format(
			files["model"], files["profile"], data["center"], url, data["machinecode_name"]))

		# Defining the function that sends the files to the PrePrintService
		# https://github.com/ChristophSchranz/Pre-Print-Service
		def post_to_preprintserver(url, files, data):
			r = requests.post(url, files=files, data=data)
			self._logger.info("POST to service with {}".format(r.status_code))
			if r.status_code in [200, 201]:
				self._logger.info("posted request successfully to {}".format(url))
			else:
				self._logger.error("Got http error code {} on request {}".format(r.status_code, url))
				self._logger.error(r.text)
				self._logger.info("Couldn't post to {}".format(url))
				return False, "Couldn't post to {}, status code {}".format(url, r.status_code)

		import threading
		slicer_worker_thread = threading.Thread(target=post_to_preprintserver, args=(url, files, data))
		slicer_worker_thread.daemon = True
		slicer_worker_thread.start()

		# Check for cancellations
		# with self._cancelled_jobs_mutex:
		# 	if machinecode_path in self._cancelled_jobs:
		# 		self._logger.info("machine code in job mutex")
		# 		self._cancelled_jobs.remove(machinecode_path)
		# with self._slicing_commands_mutex:
		# 	if machinecode_path in self._slicing_commands:
		# 		self._logger.info("machine code in slicing mutex")
		# 		print(self._slicing_commands.items())
		# 		del self._slicing_commands[machinecode_path]

		analysis = get_analysis_from_gcode(machinecode_path)
		self._logger.info("Analysis found in gcode: %s" % str(analysis))
		if analysis:
			analysis = {'analysis': analysis}
			return True, analysis

	def cancel_slicing(self, machinecode_path):
		with self._slicing_commands_mutex:
			if machinecode_path in self._slicing_commands:
				with self._cancelled_jobs_mutex:
					self._cancelled_jobs.append(machinecode_path)
				self._slicing_commands[machinecode_path].terminate()
				self._logger.info("Cancelled slicing of %s" % machinecode_path)

	def _load_profile(self, path):
		profile, display_name, description = Profile.from_slic3r_ini(path)
		return profile, display_name, description

	def _save_profile(self, path, profile, allow_overwrite=True, display_name=None, description=None):
		if not allow_overwrite and os.path.exists(path):
			raise IOError("Cannot overwrite {path}".format(path=path))
		Profile.to_slic3r_ini(profile, path, display_name=display_name, description=description)


def _sanitize_name(name):
	if name is None:
		return None

	if "/" in name or "\\" in name:
		raise ValueError("name must not contain / or \\")

	import string
	valid_chars = "-_.() {ascii}{digits}".format(ascii=string.ascii_letters, digits=string.digits)
	sanitized_name = ''.join(c for c in name if c in valid_chars)
	sanitized_name = sanitized_name.replace(" ", "_")
	return sanitized_name.lower()


def get_analysis_from_gcode(machinecode_path):
	"""Extracts the analysis data structure from the gocde.
	The analysis structure should look like this:
	http://docs.octoprint.org/en/master/modules/filemanager.html#octoprint.filemanager.analysis.GcodeAnalysisQueue
	(There is a bug in the documentation, estimatedPrintTime should be in seconds.)
	Return None if there is no analysis information in the file.
	"""
	filament_length = None
	filament_volume = None
	printing_seconds = None
	with open(machinecode_path) as gcode_lines:
		for gcode_line in gcode_lines:
			m = re.match('\s*;\s*filament used\s*=\s*([0-9.]+)\s*mm\s*\(([0-9.]+)cm3\)\s*', gcode_line)
			if m:
				filament_length = float(m.group(1))
				filament_volume = float(m.group(2))
			m = re.match('\s*;\s*estimated printing time\s*=\s(.*)\s*', gcode_line)
			if m:
				time_text = m.group(1)
				# Now extract the days, hours, minutes, and seconds
				printing_seconds = 0
				for time_part in time_text.split(' '):
					for unit in [("h", 60*60),
								("m", 60),
								("s", 1),
								("d", 24*60*60)]:
						m = re.match('\s*([0-9.]+)' + re.escape(unit[0]), time_part)
						if m:
							printing_seconds += float(m.group(1)) * unit[1]
	# Now build up the analysis struct
	analysis = None
	if printing_seconds is not None or filament_length is not None or filament_volume is not None:
		dd = lambda: defaultdict(dd)
		analysis = dd()
		if printing_seconds is not None:
			analysis['estimatedPrintTime'] = printing_seconds
		if filament_length is not None:
			analysis['filament']['tool0']['length'] = filament_length
		if filament_volume is not None:
			analysis['filament']['tool0']['volume'] = filament_volume
		return json.loads(json.dumps(analysis)) # We need to be strict about our return type, unfortunately.
	return None


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "Preprintservice Plugin"


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = PreprintservicePlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		# "octoprint.filemanager.preprocessor": __plugin_implementation__.do_slice,
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
		# "octoprint.accesscontrol.keyvalidator": __plugin_implementation__.hook
	}

