"""
Create Database Tables Using Direct Connection
This script connects directly to the Heroku PostgreSQL database using the credentials you provided
"""

import psycopg2
import sys

def create_database_tables():
    """Create all database tables using direct connection"""
    
    # Database connection details from your Heroku Postgres
    db_config = {
        'host': 'cee3ebbhveeoab.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com',
        'database': 'da08fj903lnieb',
        'user': 'ud42f690nq7vcd',
        'password': 'pd700ef90b356bf40cd4d8a555b7976ca7cef9f67c0176e82a6659199bb174ff2',
        'port': 5432
    }
    
    print("Connecting to Heroku PostgreSQL database...")
    print("=" * 50)
    
    try:
        # Connect to the database
        conn = psycopg2.connect(**db_config)
        conn.autocommit = True
        cur = conn.cursor()
        
        print("Connected successfully!")
        
        # SQL commands to create tables
        sql_commands = [
            ('UUID Extension', 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'),
            
            ('Master Templates Table', '''
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
            
            ('Template Data Table', '''
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
            
            ('Generated Certificates Table', '''
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
            
            ('Certificate Holders Table', '''
                CREATE TABLE IF NOT EXISTS certificate_holders (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    account_id VARCHAR(18) NOT NULL,
                    name VARCHAR(255),
                    email VARCHAR(255),
                    address TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            '''),
            
            ('Database Indexes', '''
                CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);
                CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);
                CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);
                CREATE INDEX IF NOT EXISTS idx_generated_certificates_account ON generated_certificates(account_id);
                CREATE INDEX IF NOT EXISTS idx_certificate_holders_account ON certificate_holders(account_id);
            ''')
        ]
        
        success_count = 0
        
        for name, sql in sql_commands:
            try:
                print(f"Creating: {name}...")
                cur.execute(sql)
                print(f"SUCCESS: {name} created!")
                success_count += 1
            except Exception as e:
                print(f"FAILED: {name} - {e}")
        
        # Verify tables were created
        print("\nVerifying tables...")
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('master_templates', 'template_data', 'generated_certificates', 'certificate_holders')
            ORDER BY table_name;
        """)
        
        tables = cur.fetchall()
        print(f"Tables created: {[table[0] for table in tables]}")
        
        cur.close()
        conn.close()
        
        print(f"\nResults: {success_count}/{len(sql_commands)} commands executed successfully")
        
        if success_count == len(sql_commands):
            print("\nSUCCESS: All database tables created!")
            print("Your Certificate Management System is now fully functional!")
            print("\nNext steps:")
            print("1. Visit: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001")
            print("2. Try uploading a template using the web interface")
            print("3. Run: python upload_simple.py")
            return True
        else:
            print("\nSome commands failed. Check the errors above.")
            return False
            
    except Exception as e:
        print(f"ERROR: Failed to connect to database - {e}")
        print("\nAlternative: Install Heroku CLI and run:")
        print("heroku pg:psql postgresql-clear-06606 --app pdfeditorsalesforce-49dc376497fd")
        return False

if __name__ == "__main__":
    create_database_tables()
