"""
Simple Database Table Creation Script
This will create tables one by one through the app API
"""

import requests
import json
import time

def create_table(table_name, sql):
    """Create a single table"""
    print(f"Creating table: {table_name}...")
    
    try:
        response = requests.post(
            'https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/setup',
            json={'action': 'create_tables', 'sql': sql},
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"SUCCESS: {table_name} created!")
                return True
            else:
                print(f"FAILED: {table_name} - {result.get('error')}")
                return False
        else:
            print(f"FAILED: {table_name} - HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"ERROR: {table_name} - {e}")
        return False

def main():
    print("Creating Certificate Management System Database Tables")
    print("=" * 60)
    
    # SQL commands for each table
    tables = [
        ("UUID Extension", 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'),
        
        ("Master Templates", '''
            CREATE TABLE IF NOT EXISTS master_templates (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                template_name VARCHAR(100) NOT NULL UNIQUE,
                template_type VARCHAR(50) NOT NULL,
                storage_path VARCHAR(500) NOT NULL,
                file_size INTEGER,
                form_fields JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        '''),
        
        ("Template Data", '''
            CREATE TABLE IF NOT EXISTS template_data (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                account_id VARCHAR(18) NOT NULL,
                template_id UUID REFERENCES master_templates(id),
                field_values JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                version INTEGER DEFAULT 1,
                UNIQUE(account_id, template_id)
            );
        '''),
        
        ("Generated Certificates", '''
            CREATE TABLE IF NOT EXISTS generated_certificates (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                account_id VARCHAR(18) NOT NULL,
                template_id UUID REFERENCES master_templates(id),
                certificate_name VARCHAR(255),
                storage_path VARCHAR(500),
                status VARCHAR(50) DEFAULT 'draft',
                generated_at TIMESTAMP DEFAULT NOW()
            );
        '''),
        
        ("Certificate Holders", '''
            CREATE TABLE IF NOT EXISTS certificate_holders (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                account_id VARCHAR(18) NOT NULL,
                name VARCHAR(255),
                email VARCHAR(255),
                address TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        '''),
        
        ("Indexes", '''
            CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);
            CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);
            CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);
            CREATE INDEX IF NOT EXISTS idx_generated_certificates_account ON generated_certificates(account_id);
            CREATE INDEX IF NOT EXISTS idx_certificate_holders_account ON certificate_holders(account_id);
        ''')
    ]
    
    success_count = 0
    
    for table_name, sql in tables:
        if create_table(table_name, sql):
            success_count += 1
        time.sleep(1)  # Wait 1 second between commands
    
    print(f"\nResults: {success_count}/{len(tables)} tables created successfully")
    
    if success_count == len(tables):
        print("\nSUCCESS: All database tables created!")
        print("Your Certificate Management System is now ready!")
        print("\nTest it:")
        print("1. Visit: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001")
        print("2. Try uploading a template")
        print("3. Run: python upload_simple.py")
    else:
        print("\nSome tables failed to create. Check errors above.")

if __name__ == "__main__":
    main()
