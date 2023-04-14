import os
import json
import requests
import urllib3
from pprint import pprint

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# insert your api-key here, e.g.: "1E7A2CA92550406381A176D9C8XXXXXX"
apikey = "7A583D795AF34DFA8F932D16D719026E"
model_path = 'preprintservice_src/Tweaker-3/demo_object.stl'

preprintservice_url = 'http://localhost:2304/'
octoprint_url = "http://192.168.48.43"

print(os.getcwd())

# Upload a file via API
# find the apikey in octoprint server, settings, access control
files = {'file': open(model_path, 'rb')}  # octoprint needs the field 'file'
r = requests.post(f"{octoprint_url}/api/files/local?apikey={apikey}", files=files, verify=False)
print(r.status_code)
print(r.json())
assert r.status_code == 201

# Download a file via API
# find the apikey in octoprint server, settings, access control
r = requests.get(f"{octoprint_url}/api/files/local/demo_object.stl?apikey={apikey}")
print(r.status_code)
assert r.status_code == 200
print(json.dumps(r.json(), indent=2))

# Delete a file via API
# find the apikey in octoprint server, settings, access control
r = requests.delete(f"{octoprint_url}/api/files/local/demo_object.stl?apikey={apikey}")
print(r.status_code)
print(r.text)
assert r.status_code == 204


# Upload a file via my own API of the tweak-service to octoprint
# find the apikey in octoprint server, settings, access control
r = requests.post(preprintservice_url, 
                  files= {'model': open(model_path, 'rb')}, 
                  data={"octoprint_url": f"{octoprint_url}/api/files/local?apikey={apikey}",
                        "tweak_option": "tweak_extended_volume_returntweaked",
                        })
print(r.status_code)
assert r.status_code == 200

# Slicing API
# find the apikey in octoprint server, settings, access control
# this step requires an installed PrePrintService Plugin in Octoprint that is correctly configured
r = requests.get(f"{octoprint_url}/api/slicing?apikey={apikey}")
print(r.status_code)
print(json.dumps(r.json(), indent=2))

print("\nAll tests succeeded.")
