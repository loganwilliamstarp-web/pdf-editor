"""
Initialize Database via Heroku App API
This script calls your deployed Heroku app to set up the database and Supabase storage
"""

import requests
import json

def initialize_system():
    """Initialize the database and Supabase storage via the Heroku app"""
    url = "https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/setup"
    
    try:
        print("Initializing Certificate Management System...")
        print(f"Calling: {url}")
        
        response = requests.post(url, json={})
        
        if response.status_code == 200:
            result = response.json()
            print("âœ… System initialization successful!")
            print(json.dumps(result, indent=2))
            return True
        else:
            print(f"âŒ Error: HTTP {response.status_code}")
            print(response.text)
            return False
            
    except Exception as e:
        print(f"âŒ Error calling API: {e}")
        return False

def check_health():
    """Check if the system is healthy"""
    url = "https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/health"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            result = response.json()
            print("âœ… System is healthy!")
            print(json.dumps(result, indent=2))
            return True
        else:
            print(f"âŒ Health check failed: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"âŒ Error checking health: {e}")
        return False

def main():
    print("ðŸš€ Certificate Management System Initialization")
    print("=" * 50)
    
    # Check health first
    print("\n1. Checking system health...")
    if not check_health():
        print("âŒ System is not healthy. Please check your deployment.")
        return
    
    # Initialize the system
    print("\n2. Initializing database and storage...")
    if initialize_system():
        print("\nðŸŽ‰ System initialization complete!")
        print("\nYour Certificate Management System is now ready:")
        print("â€¢ Supabase storage configured")
        print("â€¢ Database schema created")
        print("â€¢ Ready for Salesforce integration")
        print("\nðŸ”— Next steps:")
        print("1. Set up Salesforce Remote Site Settings")
        print("2. Create Visualforce page")
        print("3. Add to Account page layout")
        print("4. Upload your ACORD templates")
    else:
        print("\nâŒ System initialization failed.")
        print("Please check the Heroku logs for details.")

if __name__ == "__main__":
    main()
