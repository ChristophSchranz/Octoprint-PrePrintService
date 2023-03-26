# OctoPrint-PrePrintService

OctoPrint-PrePrintService is a service that enhances your 3D printing workflow by automating the orientation and slicing of your 3D models.

The PrePrint Service relies on two powerful tools:

* **[Tweaker-3](https://github.com/ChristophSchranz/Tweaker-3) for auto-orientation of FDM 3D prints**
* **[Slic3r](https://slic3r.org/) for slicing**

If you are using the [Cura](https://ultimaker.com/software/ultimaker-cura) slicer instead, you can set up a similar toolchain by using the Plugins [OctoPrint Connection](https://marketplace.ultimaker.com/app/cura/plugins/fieldofview/OctoPrintPlugin) and [Auto-Orientation](https://marketplace.ultimaker.com/app/cura/plugins/nallath/OrientationPlugin).


## Workflow in OctoPrint

You can deploy the entire workflow on a single machine, or across two separate nodes, as illustrated below:

![Workflow](/extras/workflow.png)

The workflow involves the following steps:

<!-- Is the first step correct in the new layout, do we need the slicer tab? -->
1. Upload a model on OctoPrint and click on the `Slice` button in the `file bar`.
2. The model is auto-oriented for optimal 3D printing by [Tweaker-3](https://github.com/ChristophSchranz/Tweaker-3) software.
4. The oriented model is then sliced by [Slic3r](https://slic3r.org/).
5. The final machine code is sent back to the OctoPrint server.
6. You can start your print

Each step can be customized by adjusting the settings as described in the documentation.


## Requirements

1. A node that is connected to your 3D printer referred to as the printer node, like a Raspberry Pi.
2. One server node for pre-processing with at least a 2 GHz CPU frequency. If the node connected to the printer is powerful enough, this one can do both parts.
3. Optional: Install [Docker](https://www.docker.com/) version **1.10.0+**
   and [Docker Compose](https://docs.docker.com/compose/install/) version **1.6.0+**
   on the more powerful node.


## Setup

### 1. Install the Plugin

Install the **OctoPrint-PrePrint Service** via the [Plugin Manager](http://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html) from the Plugin Repository `https://plugins.octoprint.org/plugins/preprintservice/` 
or manually using the URL on the Printer-Controller


### 2. Set up the service in Docker

To make the service highly available, it is recommended to deploy the PrePrint-Service in Docker..

Then run the application locally with:

    git clone https://github.com/christophschranz/OctoPrint-PrePrintService --recurse-submodules
    cd OctoPrint-PrePrintService
    docker-compose up --build -d
    docker-compose logs -f

**Optional:** The `docker-compose.yml`  is also configured to run in a given Docker swarm. Adapt the `docker-compose.yml` to your setup and run:

    docker-compose build
    docker-compose push
    docker stack deploy --compose-file docker-compose.yml preprintservice

In both cases, the service is available at [localhost:2304/tweak](http://localhost:2304/tweak) (at the server node), where a simple UI is provided for testing the PrePrint Service. Use `docker-compose down` to stop the service. (If you ever wish :wink: )

![PrePrint Service](/extras/PrePrintService.png)


<!-- improve from here on -->
## Configuration

Configure the plugin in the settings and make sure the url for the PrePrint service is set
correctly.

Finally, go back to the home UI, **click** on the **`Slice`-Button** of uploaded STL-Models and
**produce printable machinecode** via this Preprocessing-Plugin.

## Testing

To test the whole setup, do the following steps:

1. Visit [localhost:2304/tweak](http://localhost:2304/tweak), select a stl model file
   and make an extended Tweak (auto-rotation) `without` slicing. The output should be
   an auto-rotated (binary) STL model. If not, check the logs of the docker-service
   using `docker-compose logs -f` in the folder where the `docker-compose.yml` is located.

2. Now, do the same `with` slicing, the resulting file should be a gcode file of the model.
   Else, check the logs of the docker-service using `docker-compose logs -f` in the
   same folder.

3. Visit the OctoPrint server, click on the **`Slice`-Button** of the uploaded
   STL-Model in the `file bar` and **produce printable machinecode** via this
   PrePrint-Service Plugin.. After some seconds a `.gco` file should be uploaded.
   If this doesn't work, start the OctoPrint server per CLI with `octoprint serve`
   and track the logs via `tail -f .octoprint/logs/octoprint.log`. The following two lines are expected:

        2019-04-07 22:28:44,301 - octoprint.plugins.preprintservice - INFO - Connection to PrePrintService on http://192.168.48.81:2304/tweak is ready, status code 200

   If the the PrePrint Server can't be reached, you will see this:

        2019-04-07 22:27:34,746 - octoprint.plugins.preprintservice - WARNING - Connection to PrePrint Server on http://192.168.48.81:2304/tweak couldn't be established

   Make also sure that your selected `profile` file is correct. An invalid profile would look result in:

        2020-02-05 21:20:28,777 - octoprint.plugins.preprintservice - ERROR - Got http error code 500 on request http://192.168.48.48:2304/tweak
        2020-02-05 21:20:28,778 - octoprint.plugins.preprintservice - INFO - Couldn't post to http://192.168.48.48:2304/tweak

If you have any troubles in setting this plugin up or tips to improve this instruction, please let me know!

## PrePrint-Service API

You can use this API to preprocess your models for 3D printing.

```python
import requests

url = "http://localhost:2304/tweak"
model_path = 'preprintservice_src/uploads/model.stl'
profile_path = 'preprintservice_src/profiles/profile_015mm_brim.profile'
output_path = 'gcode_name.gcode'

# Auto-rotate file without slicing
r = requests.post(url, files={'model': open(model_path, 'rb')},
                  data={"tweak_actions": "tweak"})

# Only slice the model to a gcode
r = requests.post(url, files={'model': open(model_path, 'rb'),
                              'profile': open(profile_path, 'rb')},
                data={"machinecode_name": output_path,
                        "tweak_actions": "slice"})
# Auto-rotate and slice the model file
r = requests.post(url, files={'model': open(model_path, 'rb'), 'profile': open(profile_path, 'rb')},
                  data={"machinecode_name": output_path, "tweak_actions": "tweak slice"})
print(r.status_code)
object = r.text
```

The resulting object, either a tweaked stl file or a gcode file is
accessible via `r.text` which can be some MB large.

Information of how to interact with OctoPrint's API is depicted [here](http://docs.octoprint.org/en/master/api/files.html#upload-file-or-create-folder).
For example, you can test the file upload API like this:

```python
import json
import requests

# OctoPrint's URL using the default port 5000 and the API including the API-key
url = "http://192.168.48.43:5000/api/files/local?apikey=A943AB47727A461XXXXXXXXXXXX"
model_path = 'preprintservice_src/uploads/model.stl'
files = {'file': open(model_path, 'rb')}

# Upload a file using OctoPrint's API
r = requests.post(url=url, files=files)
print(r.status_code)
print(json.dumps(r.json(), indent=2))
```

I hope this workflow for 3D print preprocessing helps you!
