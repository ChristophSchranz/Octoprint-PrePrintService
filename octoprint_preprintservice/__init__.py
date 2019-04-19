# coding=utf-8
from __future__ import absolute_import

import os
import re
import json
from collections import defaultdict

import flask
import requests
import octoprint.plugin
from octoprint.util.paths import normalize as normalize_path

from .profile import Profile

blueprint = flask.Blueprint("plugin.preprintservice", __name__)


class PreprintservicePlugin(octoprint.plugin.SlicerPlugin,
							octoprint.plugin.StartupPlugin,
							octoprint.plugin.SettingsPlugin,
							octoprint.plugin.AssetPlugin,
							octoprint.plugin.BlueprintPlugin,
							octoprint.plugin.TemplatePlugin,
							octoprint.plugin.EventHandlerPlugin):

	# ~~ StartupPlugin API
	def on_after_startup(self):
		self._logger.debug("Starting PrePrintService plugin, using settings: {}".format(self._settings.get_all_data()))

	def get_settings_defaults(self):
		return dict(url="http://localhost:2304/tweak",
					get_tweaked_stl=True,
					tweak_action="tweak slice",
					isurlok=False,
					default_profile=os.path.join(os.path.dirname(os.path.realpath(__file__)), "profiles",
												 "default_slic3r_profile.ini"),
					isapikeyok=False,
					restricted=dict(admin_only=dict(apikey="asdf")))

	def get_settings_restricted_paths(self):
		return dict(admin=[["restricted", "admin_only", "apikey"]])

	def get_template_vars(self):
		return dict(url=self._settings.get(["url"]),
					get_tweaked_stl=self._settings.get_boolean(["get_tweaked_stl"]),
					tweak_action=self._settings.get(["tweak_action"]))

	def get_template_configs(self):
		return [
			dict(type="navbar", custom_bindings=False),
			dict(type="settings", custom_bindings=True)
			# dict(type="sidebar", template="dialogs/preprintservice_sidebar.jinja2", custom_bindings=True)
		]

	# ~~ SettingsPlugin mixin
	def on_settings_save(self, data):
		self._logger.debug("on_settings_save was called")
		old_url = self._settings.get(["url"]).strip()
		old_apikey = self._settings.get(["apikey"]).strip()
		old_tweakaction = self._settings.get(["tweak_action"])
		old_gettweakedstl = self._settings.get_boolean(["get_tweaked_stl"])

		self._logger.debug("Settings: {}".format(data))
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		new_url = self._settings.get(["url"]).strip()
		if old_url != new_url:
			self._logger.info("New PrePrint Service url was set: {}".format(new_url))

		new_apikey = self._settings.get(["apikey"]).strip()
		if old_apikey != new_apikey:
			self._logger.info("New apikey set: {}".format(new_apikey))

		new_tweakaction = self._settings.get(["tweak_action"])
		if old_tweakaction != new_tweakaction:
			self._logger.info("New action for preprocessing set: {}".format(new_tweakaction))
		new_gettweakedstl = self._settings.get_boolean(["get_tweaked_stl"])
		if old_gettweakedstl != new_gettweakedstl:
			self._logger.info("New setting, getting auto-rotated stl is set to: {}".format(new_gettweakedstl))

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
					"Something went wrong while converting imported profile: {}".format(e.message), 500)

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
					"Something went wrong while converting imported profile: {}".format(e.message), 500)
			finally:
				os.remove(temp_file)

			filename = upload.filename

		else:
			return flask.make_response("No file included", 400)

		name, _ = os.path.splitext(filename)

		# default values for name, display name and description
		profile_name = _sanitize_name(name)
		profile_display_name = imported_name if imported_name is not None else name
		profile_description = imported_description if imported_description is not None \
			else "Imported from {filename} on {date}".format(
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

		self._slicing_manager.save_profile("preprintservice", profile_name, profile_dict,
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

	# EventHandlerPlugin
	def on_event(self, event, payload):
		# Extract Gcode name and set it as instance var
		if event == "SlicingStarted":
			self.machinecode_name = payload.get("gcode", None)
			# self._logger.info("\nEVENT: {}: {}\n".format(event, payload))

	# SlicerPlugin API
	def is_slicer_configured(self):
		# Try connection to PrePrintService
		url = self._settings.get(["url"]).strip()
		try:
			r = requests.get(url, timeout=2)
			if r.status_code != 200:
				self._logger.warning(
					"Connection to PrePrint Server on {} couldn't be established, status code {}"
						.format(url, r.status_code))
				return False,
		except requests.ConnectionError:
			self._logger.warning("Connection to PrePrint Server on {} couldn't be established".format(url))
			return False
		self._logger.info("Connection to PrePrintService on {} is ready, status code {}"
						  .format(url, r.status_code))

		def test_octoprint_connection():
			apikey = self._settings.get(["apikey"]).strip()
			if apikey is None:
				self._logger.warning("API KEY not configured")
				return False
			octoprint_url = "http://{}:5000/api/version?apikey={}".format(get_host_ip_address(), apikey)
			try:
				r = requests.get(octoprint_url)
				if r.status_code != 200:
					self._logger.warning(
						"Connection to Octoprint server on {} couldn't be established, status code {}"
							.format(octoprint_url, r.status_code))
					return False
			except requests.ConnectionError:
				self._logger.warning("Connection to Octoprint server on {} couldn't be established".format(octoprint_url))
				return False
			self._logger.info("Connection to Octoprint server on {} is ready, status code {}"
							  .format(octoprint_url.split("api/version?apikey")[0], r.status_code))
			return True

		import threading
		test_octoprint_connection = threading.Thread(target=test_octoprint_connection, args=())
		test_octoprint_connection.daemon = True
		test_octoprint_connection.start()
		return True

	def test_url(self, url):
		# Try connection to PrePrintService
		url = url.strip()
		try:
			r = requests.get(url, timeout=2)
			if r.status_code != 200:
				self._logger.warning(
					"Connection to {} couldn't be established, status code {}".format(url, r.status_code))
				return False,
		except requests.ConnectionError:
			self._logger.warning("Connection to {} couldn't be established".format(url))
			return False
		self._logger.info("Connection to PrePrintService is ready")
		return True

	def get_slicer_properties(self):
		return dict(
			type="preprintservice",
			name="PrePrintService",
			same_device=False,
			progress_report=False)

	def get_slicer_default_profile(self):
		self._logger.debug("get_slicer_default_profile")
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
		profile_dict, display_name, description = self._load_profile(profile_path)

		# print("\n Input values: {} \n{}\n\n".format(args, kwargs))
		# print("\n\nAll data: {}\n\n".format(self._settings.get_all_data()))
		tweak_actions = list()
		if "tweak" in self._settings.get(["tweak_action"]):
			tweak_actions.append("tweak")
		if "slice" in self._settings.get(["tweak_action"]):
			tweak_actions.append("slice")
		if self._settings.get_boolean(["get_tweaked_stl"]):
			tweak_actions.append("get_tweaked_stl")
		self._logger.info("Using Tweak actions: {}".format(tweak_actions))
		# tweak_actions = ["tweak", "slice", "get_tweaked_stl"]

		# octoprint.plugin.TemplatePlugin.on_plugin_enabled()
		# machinecode_path is a string based on a random tmpfile
		if self.machinecode_name:
			machinecode_path = self.machinecode_name
		else:
			path, _ = os.path.splitext(model_path)
			machinecode_path = path + "." + display_name.split("\n")[0] + ".gcode"
		self._logger.debug("Machinecode_name: {}".format(machinecode_path))

		# Try connection to PrePrintService
		url = self._settings.get(["url"]).strip()
		try:
			r = requests.get(url)
			if r.status_code != 200:
				self._logger.warning("Connection to {} could not be established, status code {}"
									 .format(url, r.status_code))
				return False, "Connection to {} could not be established.".format(url)
		except requests.ConnectionError:
			self._logger.info("Connection to {} could not be established.".format(url))
			return False, "Connection to {} could not be established.".format(url)

		# Sending model, profile and gcodename to PrePrintService
		files = {'model': open(model_path, 'rb'),
				 'profile': open(profile_path, 'rb')}  # profile path is wrong (tmp file), but model path is correct
		data = {"machinecode_name": os.path.split(machinecode_path)[-1],
				"octoprint_url": "http://{}:5000/api/files/local?apikey={}".format(
					get_host_ip_address(), self._settings.get(["apikey"])),
				"tweak_actions": " ".join(tweak_actions)}
		self._logger.info("Sending file {} and profile {} to {} and get {}".format(
			model_path, profile_path, url, data.get("machinecode_name")))

		# Defining the function that sends the files to the PrePrintService
		def post_to_preprintserver(url, payload_files, payload):
			r = requests.post(url, files=payload_files, data=payload)
			self._logger.info("POST to service with status code: {}".format(r.status_code))
			if r.status_code == 200:
				self._logger.info("Posted request successfully to {}".format(url))
			else:
				self._logger.error("Got http error code {} on request {}".format(r.status_code, url))
				self._logger.error(r.text)
				self._logger.info("Couldn't post to {}".format(url))
				return False, "Couldn't post to {}, status code {}".format(url, r.status_code)

		import threading
		slicer_worker_thread = threading.Thread(target=post_to_preprintserver, args=(url, files, data))
		slicer_worker_thread.daemon = True
		slicer_worker_thread.start()

		analysis = get_analysis_from_gcode(machinecode_path)
		self._logger.info("Analysis for gcode {}: {}".format(machinecode_path, analysis))
		if analysis:
			analysis = {'analysis': analysis}
			return True, analysis

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


def get_host_ip_address():
	import socket
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	s.connect(("8.8.8.8", 80))
	ip_address = s.getsockname()[0]
	s.close()
	# return "192.168.43.187"
	return ip_address


def get_analysis_from_gcode(machinecode_path):
	"""Extracts the analysis data structure from the gocde.
	The analysis structure should look like this:
	http://docs.octoprint.org/en/master/modules/filemanager.html#octoprint.filemanager.analysis.GcodeAnalysisQueue
	(There is a bug in the documentation, estimatedPrintTime should be in seconds.)
	Return None if there is no analysis information in the file and return -1 for each value if the file is empty
	"""
	filament_length = None
	filament_volume = None
	printing_seconds = None

	try:
		_ = len(open(machinecode_path).readlines())
	except (TypeError, IOError) as e:
		# empty file was uploaded
		dd = lambda: defaultdict(dd)
		analysis = dd()
		analysis['estimatedPrintTime'] = -1
		analysis['filament']['tool0']['length'] = -1
		analysis['filament']['tool0']['volume'] = -1
		return json.loads(json.dumps(analysis))  # We need to be strict about our return type, unfortunately.

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
					for unit in [("h", 60 * 60),
								 ("m", 60),
								 ("s", 1),
								 ("d", 24 * 60 * 60)]:
						m = re.match('\s*([0-9.]+)' + re.escape(unit[0]), time_part)
						if m:
							printing_seconds += float(m.group(1)) * unit[1]

	# Now build up the analysis struct
	if printing_seconds is not None or filament_length is not None or filament_volume is not None:
		dd = lambda: defaultdict(dd)
		analysis = dd()
		if printing_seconds is not None:
			analysis['estimatedPrintTime'] = printing_seconds
		if filament_length is not None:
			analysis['filament']['tool0']['length'] = filament_length
		if filament_volume is not None:
			analysis['filament']['tool0']['volume'] = filament_volume
		return json.loads(json.dumps(analysis))  # We need to be strict about our return type, unfortunately.
	return None


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "Preprintservice Plugin"

# TODO: check validity of urls and api key
# TODO: set preprint actions in slicer dialog


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = PreprintservicePlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		# "octoprint.filemanager.preprocessor": __plugin_implementation__.do_slice,
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}
