import requests
import json

# Test the upload endpoint to see the exact error
try:
    with open('database/templates/acord25.pdf', 'rb') as f:
        files = {'file': f}
        data = {
            'name': 'Test ACORD 25',
            'template_type': 'acord25',
            'account_id': '001000000000001'
        }
        
        response = requests.post(
            'https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/upload-template',
            files=files,
            data=data
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
except Exception as e:
    print(f"Error: {e}")
