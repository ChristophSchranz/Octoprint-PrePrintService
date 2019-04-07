# OctoPrint-PrePrintService

This plugin supports your 3D printing routine by featuring **auto-rotation** and **slicing**.
As both tasks are very computation-intensive, they can optionally be outsourced to 
external docker containers.


## Requirements

0. One server node that is connected to your 3D printer
1. One server node for pre-processing, which has at least 2GHz CPU frequency. If the node connected
   to the printer is strong enough, one server suffices.
1. Install [Docker](https://www.docker.com/community-edition#/download) version **1.10.0+**
   on the more powerful node.
2. Install [Docker Compose](https://docs.docker.com/compose/install/) version **1.6.0+**
   on the more powerful node.
3. Optionally: [Docker Swarm](https://www.youtube.com/watch?v=x843GyFRIIY)


## Setup

###1. Install the Plugin

Install via the bundled [Plugin Manager](http://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL on the Printer-Controller

    pip install "https://github.com/christophschranz/OctoPrint-PrePrintService/archive/master.zip"
    
When opening octoprint, you see that everything worked, if there stands `Using PrePrint Service`
in the navigation bar.
![OctoPrint_navbar](https://github.com/ChristophSchranz/Octoprint-PrePrintService/blob/master/extras/OctoPrint_navbar.png)


###2. Install the PrePrint Service

In order to make the service highly available, the PrePrint Service should be deployed
 in docker. If you are
not yet familiar with docker, have a quick look at the links in the 
[requirements](#requirements) and install it on a free and performant server node.

Then run the application locally with:

    docker-compose up --build -d
    docker-compose logs -f
     
The `docker-compose.yml` is also configured to run in a given docker swarm, therefore run:

    docker-compose build
    docker-compose push
    docker stack deploy --compose-file docker-compose.yml preprintservice


The service is available for both setups on [localhost:2304/tweak](http://localhost:2304/tweak), 
where a simple UI is provided for testing the PrePrint Service.
Use `docker-compose down` to stop the service.

![PrePrint Service](https://github.com/ChristophSchranz/Octoprint-PrePrintService/blob/master/extras/PrePrintService.png)


## Configuration

Configure the plugin in the settings and make sure the url for the PrePrint service is 
correct:

![settings](https://github.com/ChristophSchranz/Octoprint-PrePrintService/blob/master/extras/settings.png)

To test the configuration, do the following steps:

1. Visit [localhost:2304/tweak](http://localhost:2304/tweak), select a stl model file
   and make an extended Tweak (auto-rotation) `without` slicing. The output should be
   the auto-rotated binary STL model. Else, check the logs of the docker-service
   using `docker-compose logs -f` in the same folder.

2. Now do the same `with` slicing, the resulting file should be a gcode file of the model.
   Else, check the logs of the docker-service using `docker-compose logs -f` in the 
   same folder.

3. Visit the octoprint server and try to slice an uploaded stl model file. After
   some seconds a `.gco` file should be uploaded. Note that in a small time frame a
   `.gco` file with only one line and 83 bytes can appear. This one should be overwritten
   soon afterwards.
   If this doesn't work, start the octoprint server per CLI with `octoprint serve`
   and track the logs. The following two lines are expected:
   
        2019-04-07 21:47:08,066 - octoprint.plugins.preprintservice - INFO - Connection to PrePrintService is ready
        2019-04-07 21:47:08,080 - octoprint.plugins.preprintservice - INFO - Connection to http://192.168.43.187:5000/api/version?apikey=A943AB47727A461F9CEF9EXXXXXXXX is established, status code 200 

   If you see instead the following, please check the APIKEY:
        
        2019-04-07 21:46:58,524 - tornado.access - WARNING - 403 GET /api/version?apikey=asdfasdfasdf (192.168.43.187) 5.05ms
        2019-04-07 21:46:58,527 - octoprint.plugins.preprintservice - WARNING - Connection to http://192.168.43.187:5000/api/version?apikey=asdfasdfasdf couldn't be established, status code 403
        
   If the the PrePrint Server can't be reached, you will seee this:
   
        2019-04-07 21:51:28,454 - octoprint.plugins.preprintservice - WARNING - Connection to http://localhost:2305/ couldn't be established

   
If you have any troubles in setting this plugin up or tips to improve this instruction,
 please let me know!


## Donation

If you like this plugin, you can buy me a cup of coffee :) 

[![More coffee, more code](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=RG7UBJMUNLMHN&source=url)

Happy Printing!
