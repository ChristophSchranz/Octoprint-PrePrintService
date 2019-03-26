# coding=utf-8
from __future__ import absolute_import

import logging
import logging.handlers

import os
import re
import json
import flask
from collections import defaultdict
from pkg_resources import parse_version

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
							octoprint.plugin.TemplatePlugin):

	# ~~ StartupPlugin API

	def on_after_startup(self):
		self._logger.info("Hello from the PrePrintService plugin! (more: %s)" % self._settings.get(["url"]))

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

		self._slicing_manager.save_profile("slic3r",  profile_name, profile_dict,
										   allow_overwrite=profile_allow_overwrite,
										   display_name=profile_display_name,
										   description=profile_description)

		result = dict(
			resource=flask.url_for("api.slicingGetSlicerProfile", slicer="slic3r", name=profile_name,
								   external=True),
			displayName=profile_display_name,
			description=profile_description
		)
		r = flask.make_response(flask.jsonify(result), 201)
		r.headers["Location"] = result["resource"]
		return r

	##~~ SlicerPlugin API

	def is_slicer_configured(self):
		#slic3r_engine = normalize_path(self._settings.get(["slic3r_engine"]))
		# return slic3r_engine is not None and os.path.exists(slic3r_engine)
		return True

	def get_slicer_properties(self):
		self._logger.info("get_slicer_properties")
		return dict(
			type="PrePrintService",
			name="PrePrintService",
			same_device=True,
			progress_report=False
		)

	def get_slicer_default_profile(self):
		self._logger.info("get_slicer_default_profile")
		path = self._settings.get(["default_profile"])
		if not path:
			path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "profiles", "default_slic3r_profile.ini")
		return self.get_slicer_profile(path)

	def get_slicer_profile(self, path):
		self._logger.info("get_slicer_profile")
		profile_dict, display_name, description = self._load_profile(path)
		properties = self.get_slicer_properties()
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
				 on_progress=None, on_progress_args=None, on_progress_kwargs=None):
		if not profile_path:
			profile_path = self._settings.get(["default_profile"])
		if not machinecode_path:
			path, _ = os.path.splitext(model_path)
			machinecode_path = path + ".gco"

		if position and isinstance(position, dict) and "x" in position and "y" in position:
			posX = position["x"]
			posY = position["y"]
		elif printer_profile["volume"]["formFactor"] == "circular" or printer_profile["volume"]["origin"] == "center":
			posX = 0
			posY = 0
		else:
			posX = printer_profile["volume"]["width"] / 2.0
			posY = printer_profile["volume"]["depth"] / 2.0

		self._logger.info(
			"### Slicing %s to %s using profile stored at %s" % (model_path, machinecode_path, profile_path))

		executable = normalize_path(self._settings.get(["slic3r_engine"]))
		if not executable:
			self._logger.info("No Slic3r found")
			return False, "Path to Slic3r is not configured "

		import sarge

		working_dir, _ = os.path.split(executable)
		args = ['"%s"' % executable, '--load', '"%s"' % profile_path, '--print-center', '"%f,%f"' % (posX, posY), '-o',
				'"%s"' % machinecode_path, '"%s"' % model_path]

		command = " ".join(args)
		self._logger.info("Running %r in %s" % (command, working_dir))
		try:
			if parse_version(sarge.__version__) >= parse_version(
					'0.1.5'):  # Because in version 0.1.5 the name was changed in sarge.
				async_kwarg = 'async_'
			else:
				async_kwarg = 'async'
			p = sarge.run(command, cwd=working_dir, stdout=sarge.Capture(), stderr=sarge.Capture(),
						  **{async_kwarg: True})
			p.wait_events()
			try:
				with self._slicing_commands_mutex:
					self._slicing_commands[machinecode_path] = p.commands[0]

				line_seen = False
				while p.returncode is None:
					stdout_line = p.stdout.readline(timeout=0.5)
					stderr_line = p.stderr.readline(timeout=0.5)

					if not stdout_line and not stderr_line:
						if line_seen:
							break
						else:
							continue

					line_seen = True
					if stdout_line:
						self._logger.debug("stdout: " + stdout_line.strip())
					if stderr_line:
						self._logger.debug("stderr: " + stderr_line.strip())
			finally:
				p.close()

			with self._cancelled_jobs_mutex:
				if machinecode_path in self._cancelled_jobs:
					self._logger.info("### Cancelled")
					raise octoprint.slicing.SlicingCancelled()

			self._logger.info("### Finished, returncode %d" % p.returncode)
			if p.returncode == 0:
				analysis = get_analysis_from_gcode(machinecode_path)
				self._logger.info("Analysis found in gcode: %s" % str(analysis))
				if analysis:
					analysis = {'analysis': analysis}
				return True, analysis
			else:
				self._logger.warn("Could not slice via Slic3r, got return code %r" % p.returncode)
				return False, "Got returncode %r" % p.returncode

		except octoprint.slicing.SlicingCancelled as e:
			raise e
		except:
			self._logger.exception("Could not slice via Slic3r, got an unknown error")
			return False, "Unknown error, please consult the log file"

		finally:
			with self._cancelled_jobs_mutex:
				if machinecode_path in self._cancelled_jobs:
					self._cancelled_jobs.remove(machinecode_path)
			with self._slicing_commands_mutex:
				if machinecode_path in self._slicing_commands:
					del self._slicing_commands[machinecode_path]

			self._logger.info("-" * 40)

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
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}

