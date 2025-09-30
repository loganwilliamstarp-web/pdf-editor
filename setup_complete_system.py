import requests
import os
from pathlib import Path

APP_URL = "https://pdfeditorsalesforce-49dc376497fd.herokuapp.com"
TEMPLATES_DIR = "database/templates"
TEST_ACCOUNT_ID = "001000000000001"

def test_connection():
    print("Testing connection...")
    try:
        response = requests.get(f"{APP_URL}/api/health", timeout=10)
        if response.status_code == 200:
            print("SUCCESS: Connection successful!")
            return True
        else:
            print(f"ERROR: Connection failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"ERROR: Connection error: {e}")
        return False

def upload_templates():
    templates_dir = Path(TEMPLATES_DIR)
    if not templates_dir.exists():
        print(f"ERROR: Templates directory not found: {TEMPLATES_DIR}")
        return False
    
    pdf_files = list(templates_dir.glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF templates")
    
    acord_names = {
        "acord25.pdf": "ACORD 25 - Certificate of Liability Insurance",
        "acord27.pdf": "ACORD 27 - Evidence of Property Insurance",
        "acord28.pdf": "ACORD 28 - Evidence of Commercial Property Insurance",
        "acord30.pdf": "ACORD 30 - Evidence of Insurance",
        "acord35.pdf": "ACORD 35 - Evidence of Property Insurance",
        "acord36.pdf": "ACORD 36 - Evidence of Insurance",
        "acord37.pdf": "ACORD 37 - Evidence of Insurance",
        "acord125.pdf": "ACORD 125 - Evidence of Insurance",
        "acord126.pdf": "ACORD 126 - Evidence of Insurance",
        "acord130.pdf": "ACORD 130 - Evidence of Insurance",
        "acord140.pdf": "ACORD 140 - Evidence of Insurance"
    }
    
    successful = 0
    for pdf_file in sorted(pdf_files):
        filename = pdf_file.name
        template_name = acord_names.get(filename.lower(), filename.replace(".pdf", "").replace("_", " ").title())
        
        print(f"Uploading {filename}...")
        
        try:
            with open(pdf_file, 'rb') as f:
                files = {'file': (filename, f, 'application/pdf')}
                data = {'name': template_name, 'account_id': TEST_ACCOUNT_ID}
                
                response = requests.post(f"{APP_URL}/api/provision-pdf", files=files, data=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"  SUCCESS: {filename} uploaded")
                    successful += 1
                else:
                    print(f"  ERROR: {filename} failed: {result.get('error')}")
            else:
                print(f"  ERROR: {filename} HTTP error: {response.status_code}")
        except Exception as e:
            print(f"  ERROR: {filename} exception: {e}")
    
    print(f"\nUpload Results: {successful}/{len(pdf_files)} successful")
    return successful > 0

def main():
    print("Certificate Management System Setup")
    print("=" * 50)
    
    if not test_connection():
        print("Cannot proceed without connection")
        return
    
    if upload_templates():
        print("\nSetup complete!")
        print(f"Test your app: {APP_URL}/{TEST_ACCOUNT_ID}")
        print("\nNext: Set up Salesforce integration")
        print("1. Go to Setup -> Security -> Remote Site Settings")
        print(f"2. Add: {APP_URL}")
        print("3. Create Visualforce page with iframe")
    else:
        print("Template upload failed")

if __name__ == "__main__":
    main()
