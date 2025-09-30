"""
Correct Template Upload Script
Uploads ACORD templates as MASTER templates (stored once, reused for all accounts)
Template data is stored separately by Salesforce Account ID
"""

import os
import sys
import io
import uuid

try:
    from supabase import create_client
    from pypdf import PdfReader
    import psycopg2
    from psycopg2.extras import Json
    print("All dependencies available")
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

def get_supabase_client():
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        return None
    
    return create_client(supabase_url, supabase_key)

def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("Missing DATABASE_URL environment variable")
        return None
    
    return psycopg2.connect(database_url, sslmode='require')

def create_database_schema():
    """Create the correct database schema for template management"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Master Templates Table - Templates stored once, reused
        cur.execute('''
            CREATE TABLE IF NOT EXISTS master_templates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                template_name VARCHAR(100) NOT NULL UNIQUE,  -- e.g., 'ACORD 25', 'ACORD 27'
                template_type VARCHAR(50) NOT NULL,           -- e.g., 'acord25', 'acord27'
                storage_path VARCHAR(500) NOT NULL,           -- Path in Supabase Storage
                file_size INTEGER,
                form_fields JSONB,                            -- Extracted form fields
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        ''')
        
        # Template Data by Account - Account-specific filled data
        cur.execute('''
            CREATE TABLE IF NOT EXISTS template_data (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                account_id VARCHAR(18) NOT NULL,              -- Salesforce Account ID
                template_id UUID REFERENCES master_templates(id),
                field_values JSONB NOT NULL,                  -- Account-specific field values
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                version INTEGER DEFAULT 1,
                UNIQUE(account_id, template_id)               -- One set of data per account per template
            );
        ''')
        
        # Legacy table for backward compatibility
        cur.execute('''
            CREATE TABLE IF NOT EXISTS master_certificates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                account_id VARCHAR(18),
                name VARCHAR(255),
                storage_path VARCHAR(500),
                file_size INTEGER,
                fields JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        ''')
        
        # Create indexes for performance
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);')
        
        conn.commit()
        print("Database schema created successfully")
        return True
        
    except Exception as e:
        print(f"Error creating database schema: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            cur.close()
            conn.close()

def upload_master_template(file_path, template_name, template_type):
    """Upload a master template (stored once, reused for all accounts)"""
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return None

    try:
        with open(file_path, 'rb') as f:
            pdf_bytes = f.read()

        # Extract form fields from PDF
        reader = PdfReader(io.BytesIO(pdf_bytes))
        form_fields = []
        if reader.get_fields():
            for field_name, field_data in reader.get_fields().items():
                form_fields.append({
                    'name': field_name,
                    'type': str(field_data.get('/FT', 'text')),
                    'value': str(field_data.get('/V', '')),
                    'required': field_data.get('/Ff', 0) & 2 == 2  # Check if required
                })

        # Upload to Supabase Storage (master templates folder)
        supabase = get_supabase_client()
        if not supabase:
            return None

        storage_path = f'master_templates/{template_type}.pdf'
        try:
            # Upload with overwrite to ensure we have the latest version
            supabase.storage.from_('certificates').upload(
                storage_path,
                pdf_bytes,
                {'content-type': 'application/pdf', 'upsert': 'true'}
            )
            print(f"Uploaded master template {template_name} to Supabase: {storage_path}")
        except Exception as e:
            print(f"Warning: Supabase upload failed: {e}")
            return None

        # Save master template metadata to PostgreSQL
        conn = get_db_connection()
        if not conn:
            return None

        cur = conn.cursor()
        cur.execute('''
            INSERT INTO master_templates (template_name, template_type, storage_path, file_size, form_fields)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (template_name) DO UPDATE SET
                storage_path = EXCLUDED.storage_path,
                file_size = EXCLUDED.file_size,
                form_fields = EXCLUDED.form_fields,
                updated_at = NOW()
            RETURNING id
        ''', (template_name, template_type, storage_path, len(pdf_bytes), Json(form_fields)))
        
        result_id = cur.fetchone()[0]
        conn.commit()
        print(f"Saved master template {template_name} metadata with ID: {result_id}")
        print(f"Form fields found: {len(form_fields)}")
        
        cur.close()
        conn.close()
        return result_id
        
    except Exception as e:
        print(f"Error uploading master template {template_name}: {e}")
        if conn:
            conn.rollback()
        return None

def main():
    print("ACORD Master Template Upload Script")
    print("=" * 50)
    print("Architecture:")
    print("- Master templates stored ONCE in Supabase")
    print("- Same template reused for ALL Salesforce accounts")
    print("- Account-specific data stored separately by account_id")
    print("=" * 50)
    
    # Check environment variables
    if not os.environ.get('DATABASE_URL'):
        print("DATABASE_URL environment variable not set")
        return
    
    if not os.environ.get('SUPABASE_URL'):
        print("SUPABASE_URL environment variable not set")
        return
    
    if not os.environ.get('SUPABASE_KEY'):
        print("SUPABASE_KEY environment variable not set")
        return
    
    # Create database schema
    print("Setting up database schema...")
    if not create_database_schema():
        print("Failed to create database schema")
        return
    
    # Upload master templates
    templates_dir = "database/templates"
    if not os.path.exists(templates_dir):
        print(f"Templates directory not found: {templates_dir}")
        return
    
    uploaded_count = 0
    
    print(f"Uploading master templates from {templates_dir}...")
    
    # Map of template files to their proper names and types
    template_mapping = {
        'acord25.pdf': ('ACORD 25 - Certificate of Liability Insurance', 'acord25'),
        'acord27.pdf': ('ACORD 27 - Evidence of Property Insurance', 'acord27'),
        'acord28.pdf': ('ACORD 28 - Evidence of Commercial Property Insurance', 'acord28'),
        'acord30.pdf': ('ACORD 30 - Evidence of Commercial Crime Insurance', 'acord30'),
        'acord35.pdf': ('ACORD 35 - Evidence of Commercial Inland Marine Insurance', 'acord35'),
        'acord36.pdf': ('ACORD 36 - Evidence of Commercial Auto Insurance', 'acord36'),
        'acord37.pdf': ('ACORD 37 - Evidence of Commercial Auto Insurance', 'acord37'),
        'acord125.pdf': ('ACORD 125 - Certificate of Liability Insurance', 'acord125'),
        'acord126.pdf': ('ACORD 126 - Certificate of Liability Insurance', 'acord126'),
        'acord130.pdf': ('ACORD 130 - Evidence of Commercial Property Insurance', 'acord130'),
        'acord140.pdf': ('ACORD 140 - Evidence of Commercial Property Insurance', 'acord140')
    }
    
    for filename in os.listdir(templates_dir):
        if filename.endswith('.pdf') and filename.lower() in template_mapping:
            file_path = os.path.join(templates_dir, filename)
            template_name, template_type = template_mapping[filename.lower()]
            
            print(f"\nProcessing {filename} as {template_name}...")
            result = upload_master_template(file_path, template_name, template_type)
            
            if result:
                uploaded_count += 1
                print(f"Successfully uploaded master template: {template_name}")
            else:
                print(f"Failed to upload master template: {template_name}")
    
    print(f"\nUpload complete! {uploaded_count} master templates uploaded successfully.")
    print("\nNext steps:")
    print("1. Set Heroku environment variables")
    print("2. Visit your app: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/")
    print("3. Templates are now available for ALL Salesforce accounts")
    print("4. Each account will have their own filled data stored separately")

if __name__ == '__main__':
    main()
