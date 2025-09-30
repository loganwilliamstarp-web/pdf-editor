"""
Simple Template Upload Script (No Unicode)
Upload ACORD templates to Supabase using default bucket
"""

import os
import requests
from pathlib import Path

def upload_template(template_path, template_name, template_type):
    """Upload a template via the Heroku app API"""
    try:
        print(f"Uploading {template_name}...")
        
        with open(template_path, 'rb') as f:
            files = {'file': f}
            data = {
                'name': template_name,
                'template_type': template_type,
                'account_id': '001000000000001'
            }
            
            response = requests.post(
                'https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/upload-template',
                files=files,
                data=data
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"SUCCESS: {template_name} uploaded")
                    return True
                else:
                    print(f"FAILED: {template_name} - {result.get('error')}")
                    return False
            else:
                print(f"FAILED: {template_name} - HTTP {response.status_code}")
                return False
                
    except Exception as e:
        print(f"ERROR uploading {template_name}: {e}")
        return False

def main():
    print("Certificate Management System - Template Upload")
    print("=" * 50)
    
    # Template directory
    templates_dir = Path("database/templates")
    
    if not templates_dir.exists():
        print(f"ERROR: Templates directory not found: {templates_dir}")
        return
    
    # Template mapping
    template_types = {
        'acord25.pdf': 'ACORD 25 - Certificate of Liability Insurance',
        'acord27.pdf': 'ACORD 27 - Evidence of Property Insurance', 
        'acord28.pdf': 'ACORD 28 - Evidence of Commercial Property Insurance',
        'acord125.pdf': 'ACORD 125 - Certificate of Liability Insurance (Short Form)',
        'acord126.pdf': 'ACORD 126 - Certificate of Liability Insurance (Long Form)'
    }
    
    uploaded_count = 0
    total_count = 0
    
    for template_file in templates_dir.glob("*.pdf"):
        total_count += 1
        template_name = template_types.get(template_file.name, template_file.stem)
        template_type = template_file.stem.lower()
        
        if upload_template(template_file, template_name, template_type):
            uploaded_count += 1
    
    print(f"\nUpload Summary:")
    print(f"Total templates: {total_count}")
    print(f"Successfully uploaded: {uploaded_count}")
    print(f"Failed: {total_count - uploaded_count}")
    
    if uploaded_count > 0:
        print(f"\nTemplates uploaded successfully!")
        print(f"Visit: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001")
    else:
        print(f"\nNo templates were uploaded. Check errors above.")

if __name__ == "__main__":
    main()
