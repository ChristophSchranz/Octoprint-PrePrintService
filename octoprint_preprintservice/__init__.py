# coding=utf-8
from __future__ import absolute_import

import logging
import logging.handlers

import json
import re
from collections import defaultdict

### (Don't forget to remove me)
# This is a basic skeleton for your plugin's __init__.py. You probably want to adjust the class name of your plugin
# as well as the plugin mixins it's subclassing from. This is really just a basic skeleton to get you started,
# defining your plugin as a template plugin, settings and asset plugin. Feel free to add or remove mixins
# as necessary.
#
# Take a look at the documentation on what other plugin mixins are available.

import octoprint.plugin


class PreprintservicePlugin(octoprint.plugin.SlicerPlugin,
							octoprint.plugin.StartupPlugin,
							octoprint.plugin.SettingsPlugin,
							octoprint.plugin.AssetPlugin,
							octoprint.plugin.TemplatePlugin):

	# ~~ StartupPlugin API

	def on_after_startup(self):
		self._logger.info("Hello from the PrePrintService plugin! (more: %s)" % self._settings.get(["url"]))

	def get_settings_defaults(self):
		return dict(url="http://localhost:2304/",
					slic3r_engine=None,
					default_profile=None,
					debug_logging=False
					)

	# ~~ SettingsPlugin mixin

	def on_settings_save(self, data):
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

