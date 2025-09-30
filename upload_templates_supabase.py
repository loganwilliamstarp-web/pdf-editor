"""
Upload Templates to Supabase Default Bucket
This script uploads your ACORD templates to the default Supabase storage bucket
"""

import os
import requests
from pathlib import Path

def upload_template_via_api(template_path, template_name, template_type):
    """Upload a template via the Heroku app API"""
    try:
        print(f"Uploading {template_name}...")
        
        with open(template_path, 'rb') as f:
            files = {'file': f}
            data = {
                'name': template_name,
                'template_type': template_type,
                'account_id': '001000000000001'  # Test account ID
            }
            
            response = requests.post(
                'https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/upload-template',
                files=files,
                data=data
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"âœ… {template_name} uploaded successfully")
                    return True
                else:
                    print(f"âŒ {template_name} upload failed: {result.get('error')}")
                    return False
            else:
                print(f"âŒ {template_name} upload failed with status {response.status_code}")
                return False
                
    except Exception as e:
        print(f"âŒ Error uploading {template_name}: {e}")
        return False

def main():
    print("ðŸš€ Uploading ACORD Templates to Supabase")
    print("=" * 50)
    
    # Template directory
    templates_dir = Path("database/templates")
    
    if not templates_dir.exists():
        print(f"âŒ Templates directory not found: {templates_dir}")
        print("Please ensure your templates are in the database/templates folder")
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
        
        if upload_template_via_api(template_file, template_name, template_type):
            uploaded_count += 1
    
    print(f"\nðŸ“Š Upload Summary:")
    print(f"Total templates: {total_count}")
    print(f"Successfully uploaded: {uploaded_count}")
    print(f"Failed: {total_count - uploaded_count}")
    
    if uploaded_count > 0:
        print(f"\nðŸŽ‰ Templates uploaded successfully!")
        print(f"Visit: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001")
    else:
        print(f"\nâš ï¸  No templates were uploaded. Check the errors above.")

if __name__ == "__main__":
    main()
