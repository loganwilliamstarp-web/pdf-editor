"""
Template Upload via Web Interface
Creates a script to upload templates through the Heroku app's web interface
"""

import requests
import os
import json

def upload_template_via_api(file_path, template_name):
    """Upload template through the Heroku app API"""
    url = "https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/provision-pdf"
    
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (file_path, f, 'application/pdf')}
            data = {
                'name': template_name,
                'account_id': '001000000000001'  # Test account
            }
            
            response = requests.post(url, files=files, data=data)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"Successfully uploaded {template_name}")
                    return True
                else:
                    print(f"Upload failed: {result.get('error')}")
                    return False
            else:
                print(f"HTTP error: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"Error uploading {template_name}: {e}")
        return False

def main():
    print("Template Upload via Web Interface")
    print("=" * 50)
    
    templates_dir = "database/templates"
    if not os.path.exists(templates_dir):
        print(f"Templates directory not found: {templates_dir}")
        return
    
    # Template mapping
    template_mapping = {
        'acord25.pdf': 'ACORD 25 - Certificate of Liability Insurance',
        'acord27.pdf': 'ACORD 27 - Evidence of Property Insurance',
        'acord28.pdf': 'ACORD 28 - Evidence of Commercial Property Insurance',
        'acord30.pdf': 'ACORD 30 - Evidence of Commercial Crime Insurance',
        'acord35.pdf': 'ACORD 35 - Evidence of Commercial Inland Marine Insurance',
        'acord36.pdf': 'ACORD 36 - Evidence of Commercial Auto Insurance',
        'acord37.pdf': 'ACORD 37 - Evidence of Commercial Auto Insurance',
        'acord125.pdf': 'ACORD 125 - Certificate of Liability Insurance',
        'acord126.pdf': 'ACORD 126 - Certificate of Liability Insurance',
        'acord130.pdf': 'ACORD 130 - Evidence of Commercial Property Insurance',
        'acord140.pdf': 'ACORD 140 - Evidence of Commercial Property Insurance'
    }
    
    uploaded_count = 0
    
    print("Note: This requires the Heroku app to be running with environment variables set")
    print("If the app shows the default Heroku page, restart it first")
    print()
    
    for filename in os.listdir(templates_dir):
        if filename.endswith('.pdf') and filename.lower() in template_mapping:
            file_path = os.path.join(templates_dir, filename)
            template_name = template_mapping[filename.lower()]
            
            print(f"Uploading {filename} as {template_name}...")
            if upload_template_via_api(file_path, template_name):
                uploaded_count += 1
    
    print(f"\nUpload complete! {uploaded_count} templates uploaded successfully.")

if __name__ == '__main__':
    main()
