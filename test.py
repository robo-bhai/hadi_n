import requests

url = "https://ntfy.sh/xxc_xxx_io"
headers = {
    "Title": "Test Notification",
    "Priority": "high",
    "Tags": "rocket"
}

response = requests.post(url, data="Hello! Testing ntfy integration.".encode('utf-8'), headers=headers)
print("Response Status Code:", response.status_code)
