import os
import sys
import io
import uuid
import psycopg2
from psycopg2.extras import Json
from supabase import create_client

def get_supabase_client():
    supabase_url = "https://lpvzcfvcfckgdeuhzhrj.supabase.co"
    supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxwdmZjZnZjZmNrZ2RldWh6aHJqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MTY5OTY2OTYsImV4cCI6MTczMjU0ODY5Nn0.DJyX-3pAu6-85-6"
    return create_client(supabase_url, supabase_key)

def get_db_connection():
    return psycopg2.connect(
        host="db.lpvzcfvcfckgdeuhzhrj.supabase.co",
        port=5432,
        database="postgres",
        user="postgres",
        password="DJyX-3pAu6+85+6",
        sslmode='require'
    )

def create_database_schema():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id VARCHAR(18) PRIMARY KEY,
                name VARCHAR(255),
                billing_address TEXT,
                phone VARCHAR(50),
                email VARCHAR(255),
                last_synced TIMESTAMP DEFAULT NOW()
            );
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS master_certificates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                account_id VARCHAR(18) REFERENCES accounts(id),
                name VARCHAR(255),
                storage_path VARCHAR(500),
                file_size INTEGER,
                fields JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS pdf_field_values (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                certificate_id UUID NOT NULL,
                account_id VARCHAR(18) NOT NULL,
                field_values JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                version INTEGER DEFAULT 1,
                UNIQUE(certificate_id)
            );
        ''')
        
        cur.execute('CREATE INDEX IF NOT EXISTS idx_master_certs_account ON master_certificates(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_field_values_cert ON pdf_field_values(certificate_id);')
        
        cur.execute("INSERT INTO accounts (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", 
                   ('001000000000001', 'Test Account'))
        
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

def upload_template(file_path, account_id, template_name=None):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return None

    try:
        from pypdf import PdfReader
        
        with open(file_path, 'rb') as f:
            pdf_bytes = f.read()

        cert_id = str(uuid.uuid4())
        if template_name is None:
            template_name = os.path.basename(file_path).split('.')[0]

        reader = PdfReader(io.BytesIO(pdf_bytes))
        fields = []
        if reader.get_fields():
            for field_name, field_data in reader.get_fields().items():
                fields.append({
                    'name': field_name,
                    'type': str(field_data.get('/FT', 'text')),
                    'value': str(field_data.get('/V', ''))
                })

        supabase = get_supabase_client()
        storage_path = f'templates/{account_id}/{cert_id}.pdf'
        
        try:
            supabase.storage.from_('certificates').upload(
                storage_path,
                pdf_bytes,
                {'content-type': 'application/pdf'}
            )
            print(f"Uploaded {template_name} to Supabase: {storage_path}")
        except Exception as e:
            print(f"Warning: Supabase upload failed: {e}")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO master_certificates (id, account_id, name, storage_path, file_size, fields)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                storage_path = EXCLUDED.storage_path,
                file_size = EXCLUDED.file_size,
                fields = EXCLUDED.fields,
                updated_at = NOW()
            RETURNING id
        ''', (cert_id, account_id, template_name, storage_path, len(pdf_bytes), Json(fields)))
        
        result_id = cur.fetchone()[0]
        conn.commit()
        print(f"Saved metadata for {template_name} to PostgreSQL with ID: {result_id}")
        return result_id
        
    except Exception as e:
        print(f"Error uploading {template_name}: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            cur.close()
            conn.close()

def main():
    print("ACORD Template Upload Script")
    print("=" * 50)
    
    print("Setting up database schema...")
    if not create_database_schema():
        print("Failed to create database schema")
        return
    
    templates_dir = "database/templates"
    if not os.path.exists(templates_dir):
        print(f"Templates directory not found: {templates_dir}")
        return
    
    test_account_id = '001000000000001'
    uploaded_count = 0
    
    print(f"Uploading templates from {templates_dir}...")
    
    for filename in os.listdir(templates_dir):
        if filename.endswith('.pdf'):
            file_path = os.path.join(templates_dir, filename)
            template_name = filename.replace('.pdf', '').replace('acord', 'ACORD ').upper()
            
            print(f"\nProcessing {filename}...")
            result = upload_template(file_path, test_account_id, template_name)
            
            if result:
                uploaded_count += 1
                print(f"Successfully uploaded {template_name}")
            else:
                print(f"Failed to upload {template_name}")
    
    print(f"\nUpload complete! {uploaded_count} templates uploaded successfully.")
    print(f"Visit: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/")

if __name__ == '__main__':
    main()
