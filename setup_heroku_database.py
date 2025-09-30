"""
Setup Heroku PostgreSQL Database Tables
This script will create all the necessary tables for the Certificate Management System
"""

import requests
import json

def create_heroku_database_tables():
    """Create database tables using the Heroku app's API"""
    
    print("Setting up Heroku PostgreSQL database tables...")
    print("=" * 60)
    
    # SQL commands to create tables
    sql_commands = [
        '''
        CREATE TABLE IF NOT EXISTS master_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_name VARCHAR(100) NOT NULL UNIQUE,
            template_type VARCHAR(50) NOT NULL,
            storage_path VARCHAR(500) NOT NULL,
            file_size INTEGER,
            form_fields JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        ''',
        '''
        CREATE TABLE IF NOT EXISTS template_data (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id VARCHAR(18) NOT NULL,
            template_id UUID REFERENCES master_templates(id),
            field_values JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            version INTEGER DEFAULT 1,
            UNIQUE(account_id, template_id)
        );
        ''',
        '''
        CREATE TABLE IF NOT EXISTS generated_certificates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id VARCHAR(18) NOT NULL,
            template_id UUID REFERENCES master_templates(id),
            certificate_name VARCHAR(255),
            storage_path VARCHAR(500),
            status VARCHAR(50) DEFAULT 'draft',
            generated_at TIMESTAMP DEFAULT NOW()
        );
        ''',
        '''
        CREATE TABLE IF NOT EXISTS certificate_holders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id VARCHAR(18) NOT NULL,
            name VARCHAR(255),
            email VARCHAR(255),
            address TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        ''',
        '''
        CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);
        ''',
        '''
        CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);
        ''',
        '''
        CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);
        ''',
        '''
        CREATE INDEX IF NOT EXISTS idx_generated_certificates_account ON generated_certificates(account_id);
        ''',
        '''
        CREATE INDEX IF NOT EXISTS idx_certificate_holders_account ON certificate_holders(account_id);
        '''
    ]
    
    success_count = 0
    total_commands = len(sql_commands)
    
    for i, sql in enumerate(sql_commands, 1):
        try:
            print(f"Executing command {i}/{total_commands}...")
            
            # Use the Heroku app to execute SQL
            response = requests.post(
                'https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/setup',
                json={'action': 'create_tables', 'sql': sql},
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"SUCCESS: Command {i} executed successfully")
                    success_count += 1
                else:
                    print(f"FAILED: Command {i} - {result.get('error')}")
            else:
                print(f"FAILED: Command {i} - HTTP {response.status_code}")
                
        except Exception as e:
            print(f"ERROR: Command {i} failed - {e}")
    
    print(f"\nDatabase setup completed!")
    print(f"Successfully executed: {success_count}/{total_commands} commands")
    
    if success_count == total_commands:
        print("All database tables created successfully!")
        return True
    else:
        print("Some commands failed. Check the errors above.")
        return False

def test_database_connection():
    """Test if the database is working"""
    print("\nTesting database connection...")
    
    try:
        response = requests.get('https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/account/001000000000001/templates')
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print("SUCCESS: Database connection working!")
                print(f"Templates found: {len(result.get('templates', []))}")
                return True
            else:
                print(f"FAILED: Database query failed - {result.get('error')}")
                return False
        else:
            print(f"FAILED: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def main():
    print("Certificate Management System - Heroku PostgreSQL Setup")
    print("=" * 60)
    
    # Create database tables
    if create_heroku_database_tables():
        # Test the connection
        if test_database_connection():
            print("\nSUCCESS: Database setup complete!")
            print("Your Certificate Management System is now fully functional!")
            print("\nNext steps:")
            print("1. Visit: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001")
            print("2. Try uploading a template using the web interface")
            print("3. Run: python upload_simple.py to upload all templates")
        else:
            print("\nDatabase tables created but connection test failed.")
    else:
        print("\nDatabase setup encountered errors.")

if __name__ == "__main__":
    main()
