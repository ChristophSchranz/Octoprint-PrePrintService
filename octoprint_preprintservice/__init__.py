# coding=utf-8
from __future__ import absolute_import

import os
import re
import json
from collections import defaultdict

import flask
import requests
import urllib3

import octoprint.plugin
from octoprint.slicing import SlicingProfile
from octoprint.util.paths import normalize as normalize_path
from octoprint.filemanager.destinations import FileDestinations

try:
    from .profile import Profile
except:
    from profile import Profile

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        self.machinecode_name = None

    def get_settings_defaults(self):
        return dict(url="http://127.0.0.1:2304/tweak",
                    octoprint_url="http://127.0.0.1:5000",  # mode without port is also possible
                    apikey="find API-key under API",
                    tweak_option="tweak_extended_volume_returntweaked",
                    isurlok=False,
                    default_profile=os.path.join(os.path.dirname(os.path.realpath(__file__)), "profiles", "no_slicing"))
                                                #  "default_slic3r_profile.ini"))
    def get_template_vars(self):
        # self._logger.info(f'in get_template_vars url={self._settings.get(["url"])}')
        return dict(url=self._settings.get(["url"]),
                    request_source="octoprint",
                    tweak_option=self._settings.get(["tweak_option"]))

    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=True)
        ]

    # ~~ SettingsPlugin mixin
    def on_settings_save(self, data):
        self._logger.debug("on_settings_save was called")
        old_url = self._settings.get(["url"])
        old_octoprint_url = self._settings.get(["octoprint_url"])
        old_apikey = self._settings.get(["apikey"])

        old_tweak_option = self._settings.get(["tweak_option"])
        old_gettweakedstl = self._settings.get_boolean(["get_tweaked_stl"])

        self._logger.debug("Settings: {}".format(data))
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

        new_url = self._settings.get(["url"]).strip()
        if old_url != new_url:
            self._logger.info("New PrePrint Service url was set: {}".format(new_url))
        new_octoprint_url = self._settings.get(["octoprint_url"]).strip()
        if old_octoprint_url != new_octoprint_url:
            self._logger.info("New Octoprint Service url was set: {}".format(new_octoprint_url))
        new_apikey = self._settings.get(["apikey"]).strip()
        if old_apikey != new_apikey:
            self._logger.info("New API key was set: {}".format(new_apikey))

        new_tweak_option = self._settings.get(["tweak_option"])
        if old_tweak_option != new_tweak_option:
            self._logger.info("New tweak option for preprocessing set: {}".format(new_tweak_option))
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
                displayName="PrePrintService Plugin",
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

        print("Checking for", input_upload_name, "and", input_upload_path)
        if input_upload_name in flask.request.values and input_upload_path in flask.request.values:
            filename = flask.request.values[input_upload_name]
            try:
                profile_dict, imported_name, imported_description = Profile.from_slic3r_ini(
                    flask.request.values[input_upload_path])
            except Exception as e:
                return flask.make_response(
                    "Something went wrong while converting imported profile: {}".format(e.message), 500)

        elif input_name in flask.request.files:
            try:
                with tempfile.NamedTemporaryFile("wb", delete=False) as temp_file:
                    temp_file.close()
                    upload = flask.request.files[input_name]
                    upload.save(temp_file.name)
                    profile_dict, imported_name, imported_description = Profile.from_slic3r_ini(temp_file.name)
                    filename = upload.filename
            except Exception as e:
                return flask.make_response(
                    "Something went wrong while converting imported profile: {}".format(e.message), 500)


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
        if "localhost" in url:
            self._logger.warning("It's risky to set localhost in url, it might not work: {}".format(url))
        try:
            r = requests.get(url, timeout=2, verify=False)
            if r.status_code != 200:
                self._logger.warning(
                    "Connection to PrePrintService on {} couldn't be established, status code {}".format(url,
                                                                                                         r.status_code))
                return False
        except requests.ConnectionError:
            self._logger.warning("Connection to PrePrintService on {} couldn't be established".format(url))
            return False
        self._logger.info("Connection to PrePrintService on {} is ready, status code {}"
                          .format(url, r.status_code))
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
        return SlicingProfile(properties["type"], "unknown", profile_dict, display_name=display_name,
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

        self._logger.info("Return tweaked model: {}".format(self._settings.get(["return_tweaked"])))  # boolean
        tweak_option = self._settings.get(["tweak_option"])  # "tweak_option": "tweak_extended_volume"
        if self._settings.get(["return_tweaked"]):
            tweak_option += "_returntweaked"
        self._logger.info(f"Using Tweak option: '{tweak_option}'")
        
        # machinecode_path is a string based on a random tmpfile
        if machinecode_path is None:
            if self.machinecode_name:
                machinecode_path = self.machinecode_name
            else:
                path, _ = os.path.splitext(model_path)
                machinecode_path = path + "." + display_name.split("\n")[0] + ".gcode"
            self._logger.info("Machinecode_path: {}".format(machinecode_path))

        url = self._settings.get(["url"]).strip()
        self._logger.info("Sending file {} and profile {} to {}".format(model_path, profile_path, url))
        try:
            r = requests.post(url,
                files={
                    'model': open(model_path, 'rb'),
                    'profile': open(profile_path, 'rb'), # tmp file
                },
                data={
                    "machinecode_name": os.path.split(machinecode_path)[-1],
                    "tweak_option": tweak_option,
                    "request_source": "octoprint",
                    "octoprint_url": self._settings.get(["octoprint_url"]).strip(),
                    "apikey": self._settings.get(["apikey"]).strip()
                    # "octoprinturl": self._settings.get(["url"])  # url of the PrePrintService
                },
                verify=False)
            if r.status_code == 200:
                self._logger.info(f"Successful response from {url}; writing to {machinecode_path}")
                with open(machinecode_path, 'wb') as f:
                    f.write(r.content)
                self._logger.info(f"Wrote {len(r.content)} bytes to {machinecode_path}")
            else:
                raise Exception("Error response from {}; status code {}".format(url, r.status_code))
        except Exception as e:
            self._logger.info(e)
            return False, "Failed to slice via url {}: {}".format(url, e)

        analysis = get_analysis_from_gcode(machinecode_path)
        self._logger.info("Analysis for gcode {}: {}".format(machinecode_path, analysis))

        # Setting metadata here prevents errors when calling `has_analysis` and other metadata-fetching functions via filemanager
        self._file_manager.set_additional_metadata(FileDestinations.LOCAL, machinecode_path, "preprintservice", analysis, overwrite=True)
        self._logger.info("Set additional metadata")

        return True, {'analysis': analysis} if analysis else None

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
    dd = lambda: defaultdict(dd)
    analysis = dd()
    try:
        analysis['filament']['tool0']['length'] = -1
        analysis['filament']['tool0']['volume'] = -1
        analysis['estimatedPrintTime'] = -1
        printing_seconds = -1
        with open(machinecode_path, 'r') as f:
            for gcode_line in f:
                m = re.match('\s*;\s*filament used\s*=\s*([0-9.]+)\s*mm\s*\(([0-9.]+)cm3\)\s*', gcode_line)
                if m:
                    analysis['filament']['tool0']['length'] = float(m.group(1))
                    analysis['filament']['tool0']['volume'] = float(m.group(2))
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
        analysis['estimatedPrintTime'] = printing_seconds
    except (TypeError, IOError) as e:
        # empty file was uploaded
        print("Could not resolve analysis from file", machinecode_path, " (not found)")
    return json.loads(json.dumps(analysis))  # We need to be strict about our return type, unfortunately.


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "Preprintservice Plugin"
__plugin_pythoncompat__ = ">=2.7,<4"

# TODO: check validity of urls and api key
# TODO: set preprint actions in slicer dialog
# TODO: don't retrieve empty default .gco file if no slicing is done


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = PreprintservicePlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        # "octoprint.filemanager.preprocessor": __plugin_implementation__.do_slice,
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
