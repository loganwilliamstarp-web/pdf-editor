"""
Create Database Tables in Supabase
This script will create all the necessary tables for the Certificate Management System
"""

import requests
import json

def create_tables_via_api():
    """Create tables using Supabase SQL API"""
    
    # SQL to create all tables
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
    
    print("Creating database tables...")
    
    for i, sql in enumerate(sql_commands, 1):
        try:
            print(f"Executing command {i}/{len(sql_commands)}...")
            
            # Use the Heroku app to execute SQL
            response = requests.post(
                'https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/execute-sql',
                json={'sql': sql},
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"âœ… Command {i} executed successfully")
                else:
                    print(f"âŒ Command {i} failed: {result.get('error')}")
            else:
                print(f"âŒ Command {i} failed with status {response.status_code}")
                
        except Exception as e:
            print(f"âŒ Error executing command {i}: {e}")
    
    print("\\nDatabase table creation completed!")

def check_tables():
    """Check if tables were created successfully"""
    try:
        response = requests.get('https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/api/check-tables')
        if response.status_code == 200:
            result = response.json()
            print("\\nðŸ“Š Table Status:")
            for table, exists in result.get('tables', {}).items():
                status = "âœ…" if exists else "âŒ"
                print(f"{status} {table}")
            return result.get('tables', {})
        else:
            print(f"âŒ Failed to check tables: {response.status_code}")
            return {}
    except Exception as e:
        print(f"âŒ Error checking tables: {e}")
        return {}

def main():
    print("ðŸš€ Creating Certificate Management System Database Tables")
    print("=" * 60)
    
    # Create tables
    create_tables_via_api()
    
    # Check tables
    tables = check_tables()
    
    if all(tables.values()):
        print("\\nðŸŽ‰ All tables created successfully!")
        print("\\nYour Certificate Management System database is ready!")
    else:
        print("\\nâš ï¸  Some tables may not have been created.")
        print("\\nManual setup required:")
        print("1. Go to your Supabase dashboard")
        print("2. Open the SQL Editor")
        print("3. Run the SQL commands in create_database_tables.sql")

if __name__ == "__main__":
    main()
