import os
import json
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = 'http://localhost:2304/tweak'
model_path = 'preprintservice_src/Tweaker-3/demo_object.stl'
output_path = 'out.gcode'

print(f"current directory: {os.getcwd()}")


print("\n########### Testing the Auto-Orientation functionality ###########")

r = requests.post(url, files={'model': open(model_path, 'rb')},
                  data={"tweak_option": "tweak_keep"})
print(f"Testing tweak option: tweak_keep, statuscode {r.status_code}")
assert r.status_code == 200

r = requests.post(url, files={'model': open(model_path, 'rb')},
                  data={"machinecode_name": output_path, "tweak_option": "tweak_fast_surface"})
print(f"Testing tweak option: tweak_fast_surface, statuscode {r.status_code}")
assert r.status_code == 200

r = requests.post(url, files={'model': open(model_path, 'rb')},
                  data={"machinecode_name": output_path, "tweak_option": "tweak_fast_volume"})
print(f"Testing tweak option: tweak_fast_volume, statuscode {r.status_code}")
assert r.status_code == 200

r = requests.post(url, files={'model': open(model_path, 'rb')},
                  data={"machinecode_name": output_path, "tweak_option": "tweak_extended_surface"})
print(f"Testing tweak option: tweak_extended_surface, statuscode {r.status_code}")
assert r.status_code == 200

r = requests.post(url, files={'model': open(model_path, 'rb')},
                  data={"machinecode_name": output_path, "tweak_option": "tweak_extended_volume"})
print(f"Testing tweak option: tweak_extended_volume, statuscode {r.status_code}")
assert r.status_code == 200


print("\n########### Testing the Slicing functionality ###########")

r = requests.post(url, 
                  files={
    'model': open(model_path, 'rb'),
    'profile': open('preprintservice_src/profiles/profile_015mm_brim.ini', 'rb')
    },
    data={
    "machinecode_name": output_path, 
    "tweak_option": "tweak_keep"
    })
print(f"Testing tweak option: tweak_keep+slicing, statuscode {r.status_code}")
assert r.status_code

r = requests.post(url, files={
    'model': open(model_path, 'rb'),
    'profile': open('preprintservice_src/profiles/profile_015mm_brim.ini', 'rb')
    },
    data={
    "machinecode_name": output_path, 
    "tweak_option": "tweak_extended_volume"
    })
print(f"Testing tweak option: tweak_extended_volume+slicing, statuscode {r.status_code}")
assert r.status_code

print("\nAll tests succeeded.")
