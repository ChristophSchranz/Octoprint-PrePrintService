/*
 * View model for OctoPrint-PrePrintService
 */

$(function() {
    function PrePrintServiceViewModel(parameters) {
        var self = this;

        self.loginState = parameters[0];
        self.settingsViewModel = parameters[1];
        self.slicingViewModel = parameters[2];

        self.pathBroken = ko.observable();
        self.pathOk = ko.observable(false);
        self.pathText = ko.observable();
        self.pathHelpVisible = ko.pureComputed(function() {
            return self.pathBroken() || self.pathOk();
        });

        self.fileName = ko.observable();

        self.placeholderName = ko.observable();
        self.placeholderDisplayName = ko.observable();
        self.placeholderDescription = ko.observable();

        self.profileName = ko.observable();
        self.profileDisplayName = ko.observable();
        self.profileDescription = ko.observable();
        self.profileAllowOverwrite = ko.observable(true);

        self.uploadElement = $("#settings-preprintservice-import");
        self.uploadButton = $("#settings-preprintservice-import-start");
        self.uploadData = null;
        self.uploadButton.on("click", function() {
            if (self.uploadData) {
                self.uploadData.submit();
            }
        });

        self.profiles = new ItemListHelper(
            "plugin_preprintservice_profiles",
            {
                "id": function(a, b) {
                    if (a["key"].toLocaleLowerCase() < b["key"].toLocaleLowerCase()) return -1;
                    if (a["key"].toLocaleLowerCase() > b["key"].toLocaleLowerCase()) return 1;
                    return 0;
                },
                "name": function(a, b) {
                    // sorts ascending
                    var aName = a.name();
                    if (aName === undefined) {
                        aName = "";
                    }
                    var bName = b.name();
                    if (bName === undefined) {
                        bName = "";
                    }

                    if (aName.toLocaleLowerCase() < bName.toLocaleLowerCase()) return -1;
                    if (aName.toLocaleLowerCase() > bName.toLocaleLowerCase()) return 1;
                    return 0;
                }
            },
            {},
            "id",
            [],
            [],
            5
        );

        self._sanitize = function(name) {
            return name.replace(/[^a-zA-Z0-9\-_\.\(\) ]/g, "").replace(/ /g, "_");
        };

        self.clearUpload = function() {
            self.fileName(undefined);
            self.placeholderName(undefined);
            self.placeholderDisplayName(undefined);
            self.placeholderDescription(undefined);
            self.profileName(undefined);
            self.profileDisplayName(undefined);
            self.profileDescription(undefined);
            self.profileAllowOverwrite(true);
            self.uploadData = null;
        };

        self.uploadElement.fileupload({
            dataType: "json",
            maxNumberOfFiles: 1,
            autoUpload: false,
            headers: OctoPrint.getRequestHeaders(),
            add: function(e, data) {
                if (data.files.length == 0) {
                    return false;
                }

                self.fileName(data.files[0].name);

                var name = self.fileName().substr(0, self.fileName().lastIndexOf("."));
                self.placeholderName(self._sanitize(name).toLowerCase());
                self.placeholderDisplayName(name);
                self.placeholderDescription("Imported from " + self.fileName() + " on " + formatDate(new Date().getTime() / 1000));

                var form = {
                    allowOverwrite: self.profileAllowOverwrite()
                };
                if (self.profileName() !== undefined) {
                    form["name"] = self.profileName();
                }
                if (self.profileDisplayName() !== undefined) {
                    form["displayName"] = self.profileDisplayName();
                }
                if (self.profileDescription() !== undefined) {
                    form["description"] = self.profileDescription();
                }

                data.formData = form;
                self.uploadData = data;
            },
            done: function(e, data) {
                self.clearUpload();

                $("#settings_plugin_preprintservice_import").modal("hide");
                self.requestData();
                self.slicingViewModel.requestData();
            }
        });

        self.removeProfile = function(data) {
            if (!data.resource) {
                return;
            }

            self.profiles.removeItem(function(item) {
                return (item.key == data.key);
            });

            $.ajax({
                url: data.resource(),
                type: "DELETE",
                success: function() {
                    self.requestData();
                    self.slicingViewModel.requestData();
                }
            });
        };

        self.makeProfileDefault = function(data) {
            if (!data.resource) {
                return;
            }

            _.each(self.profiles.items(), function(item) {
                item.isdefault(false);
            });
            var item = self.profiles.getItem(function(item) {
                return item.key == data.key;
            });
            if (item !== undefined) {
                item.isdefault(true);
            }

            $.ajax({
                url: data.resource(),
                type: "PATCH",
                dataType: "json",
                data: JSON.stringify({default: true}),
                contentType: "application/json; charset=UTF-8",
                success: function() {
                    self.requestData();
                }
            });
        };

        self.showImportProfileDialog = function() {
            self.clearUpload();
            $("#settings_plugin_preprintservice_import").modal("show");
        };

        self.testEnginePath = function() {
            OctoPrint.util.testExecutable(self.settings.plugins.preprintservice.slic3r_engine())
                .done(function(response) {
                    if (!response.result) {
                        if (!response.exists) {
                            self.pathText(gettext("The path doesn't exist"));
                        } else if (!response.typeok) {
                            self.pathText(gettext("The path is not a file"));
                        } else if (!response.access) {
                            self.pathText(gettext("The path is not an executable"));
                        }
                    } else {
                        self.pathText(gettext("The path is valid"));
                    }
                    self.pathOk(response.result);
                    self.pathBroken(!response.result);
                });
        };

        self.requestData = function() {
            $.ajax({
                url: API_BASEURL + "slicing/preprintservice/profiles",
                type: "GET",
                dataType: "json",
                success: self.fromResponse
            });
        };

        self.fromResponse = function(data) {
            var profiles = [];
            _.each(_.keys(data), function(key) {
                profiles.push({
                    key: key,
                    name: ko.observable(data[key].displayName),
                    description: ko.observable(data[key].description),
                    isdefault: ko.observable(data[key].default),
                    resource: ko.observable(data[key].resource)
                });
            });
            self.profiles.updateItems(profiles);
        };

        self.onBeforeBinding = function () {
            self.settings = self.settingsViewModel.settings;
            self.requestData();
        };

        self.onSettingsHidden = function() {
            self.resetPathTest();
        };

        self.resetPathTest = function() {
            self.pathBroken(false);
            self.pathOk(false);
            self.pathText("");
        };

    }

    // view model class, parameters for constructor, container to bind to
    ADDITIONAL_VIEWMODELS.push([PrePrintServiceViewModel, ["loginStateViewModel", "settingsViewModel", "slicingViewModel"], document.getElementById("settings_plugin_preprintservice_dialog")]);
});
