import requests
import json

def test_database_connection():
    """Test the database connection through the API"""
    try:
        # Test the templates endpoint which requires database access
        response = requests.get('https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/account/001000000000001/templates')
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print("âœ… Database connection working!")
                print(f"Templates found: {len(data.get('templates', []))}")
            else:
                print(f"âŒ Database query failed: {data.get('error')}")
        else:
            print(f"âŒ HTTP error: {response.status_code}")
            
    except Exception as e:
        print(f"âŒ Error: {e}")

if __name__ == "__main__":
    print("Testing database connection...")
    test_database_connection()
