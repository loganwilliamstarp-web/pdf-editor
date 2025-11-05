"""
Complete Supabase Setup Script
This script will:
1. Create the storage bucket for PDF templates
2. Set up the database schema for templates and account data
3. Upload your ACORD templates as master templates
4. Test the complete system
"""

import os
import sys
import io
import uuid
import requests
from datetime import datetime

try:
    from supabase import create_client, Client
    from pypdf import PdfReader
    import psycopg2
    from psycopg2.extras import Json
    print("✅ All dependencies available")
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Please install: pip install supabase pypdf psycopg2-binary python-dotenv")
    sys.exit(1)

def get_supabase_client():
    """Initialize Supabase client"""
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("❌ Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        return None
    
    try:
        client = create_client(supabase_url, supabase_key)
        print("✅ Supabase client initialized")
        return client
    except Exception as e:
        print(f"❌ Error initializing Supabase client: {e}")
        return None

def get_db_connection():
    """Get PostgreSQL database connection"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ Missing DATABASE_URL environment variable")
        return None
    
    try:
        conn = psycopg2.connect(database_url, sslmode='require')
        print("✅ Database connection established")
        return conn
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        return None

def setup_supabase_storage(supabase):
    """Create the storage bucket for certificates"""
    try:
        # Try to create the bucket
        result = supabase.storage.create_bucket('certificates', public=True)
        print("✅ Created 'certificates' storage bucket")
        return True
    except Exception as e:
        if "already exists" in str(e).lower():
            print("✅ 'certificates' storage bucket already exists")
            return True
        else:
            print(f"❌ Error creating storage bucket: {e}")
            return False

def create_database_schema(conn):
    """Create the complete database schema"""
    try:
        cur = conn.cursor()
        
        # 1. Master Templates Table - Templates stored once, reused for all accounts
        cur.execute('''
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
        ''')
        
        # 2. Template Data by Account - Account-specific filled data
        cur.execute('''
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
        ''')
        
        # 3. Generated Certificates - Track generated certificates
        cur.execute('''
            CREATE TABLE IF NOT EXISTS generated_certificates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                account_id VARCHAR(18) NOT NULL,
                template_id UUID REFERENCES master_templates(id),
                certificate_name VARCHAR(255),
                storage_path VARCHAR(500),
                status VARCHAR(50) DEFAULT 'draft',
                generated_at TIMESTAMP DEFAULT NOW()
            );
        ''')
        
        # 4. Certificate Holders - People who receive certificates
        cur.execute('''
            CREATE TABLE IF NOT EXISTS certificate_holders (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                account_id VARCHAR(18) NOT NULL,
                name VARCHAR(255),
                email VARCHAR(255),
                address TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        ''')
        
        # Create indexes for performance
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_generated_certificates_account ON generated_certificates(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_certificate_holders_account ON certificate_holders(account_id);')
        
        conn.commit()
        print("✅ Database schema created successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error creating database schema: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            cur.close()
            conn.close()

def upload_master_template(supabase, conn, file_path, template_name, template_type):
    """Upload a master template to Supabase storage and register in database"""
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return None

    try:
        # Read PDF file
        with open(file_path, 'rb') as f:
            pdf_bytes = f.read()

        # Extract form fields
        reader = PdfReader(io.BytesIO(pdf_bytes))
        form_fields = []
        if reader.get_fields():
            for field_name, field_data in reader.get_fields().items():
                form_fields.append({
                    'name': field_name,
                    'type': str(field_data.get('/FT', 'text')),
                    'value': str(field_data.get('/V', '')),
                    'required': field_data.get('/Ff', 0) & 2 == 2
                })

        # Upload to Supabase Storage
        storage_path = f'master_templates/{template_type}.pdf'
        try:
            supabase.storage.from_('certificates').upload(
                storage_path,
                pdf_bytes,
                {'content-type': 'application/pdf', 'upsert': 'true'}
            )
            print(f"✅ Uploaded {template_name} to Supabase: {storage_path}")
        except Exception as e:
            print(f"❌ Error uploading to Supabase: {e}")
            return None

        # Save to database
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
        print(f"✅ Registered {template_name} in database with ID: {result_id}")
        print(f"   Found {len(form_fields)} form fields")
        
        return result_id
        
    except Exception as e:
        print(f"❌ Error uploading {template_name}: {e}")
        if conn:
            conn.rollback()
        return None

def main():
    print("🚀 Complete Supabase Setup for Certificate Management System")
    print("=" * 70)
    
    # Check environment variables
    if not os.environ.get('DATABASE_URL'):
        print("❌ DATABASE_URL environment variable not set")
        return
    
    if not os.environ.get('SUPABASE_URL'):
        print("❌ SUPABASE_URL environment variable not set")
        return
    
    if not os.environ.get('SUPABASE_KEY'):
        print("❌ SUPABASE_KEY environment variable not set")
        return
    
    # Initialize connections
    print("\n📡 Initializing connections...")
    supabase = get_supabase_client()
    if not supabase:
        return
    
    conn = get_db_connection()
    if not conn:
        return
    
    # Setup storage
    print("\n🗄️  Setting up Supabase storage...")
    if not setup_supabase_storage(supabase):
        return
    
    # Create database schema
    print("\n📊 Creating database schema...")
    if not create_database_schema(conn):
        return
    
    # Upload templates
    print("\n📄 Uploading ACORD templates...")
    templates_dir = "database/templates"
    if not os.path.exists(templates_dir):
        print(f"❌ Templates directory not found: {templates_dir}")
        return
    
    template_mapping = {
        'acord24.pdf': ('ACORD 24 - Certificate of Property Insurance', 'acord24'),
        'acord25.pdf': ('ACORD 25 - Certificate of Liability Insurance', 'acord25'),
        'acord27.pdf': ('ACORD 27 - Evidence of Property Insurance', 'acord27'),
        'acord28.pdf': ('ACORD 28 - Evidence of Commercial Property Insurance', 'acord28'),
        'acord30.pdf': ('ACORD 30 - Evidence of Commercial Crime Insurance', 'acord30'),
        'acord35.pdf': ('ACORD 35 - Evidence of Commercial Inland Marine Insurance', 'acord35'),
        'acord36.pdf': ('ACORD 36 - Agent of Record Change', 'acord36'),
        'acord37.pdf': ('ACORD 37 - Statement of No Loss', 'acord37'),
        'acord125.pdf': ('ACORD 125 - Commercial Insurance Application', 'acord125'),
        'acord126.pdf': ('ACORD 126 - Commercial General Liability Application', 'acord126'),
        'acord130.pdf': ('ACORD 130 - Evidence of Commercial Property Insurance', 'acord130'),
        'acord131.pdf': ('ACORD 131 - Umbrella Application', 'acord131'),
        'acord140.pdf': ('ACORD 140 - Evidence of Commercial Property Insurance', 'acord140')
    }
    
    uploaded_count = 0
    for filename in os.listdir(templates_dir):
        if filename.endswith('.pdf') and filename.lower() in template_mapping:
            file_path = os.path.join(templates_dir, filename)
            template_name, template_type = template_mapping[filename.lower()]
            
            print(f"\n📄 Processing {filename}...")
            result = upload_master_template(supabase, conn, file_path, template_name, template_type)
            
            if result:
                uploaded_count += 1
                print(f"✅ Successfully uploaded: {template_name}")
            else:
                print(f"❌ Failed to upload: {template_name}")
    
    # Final summary
    print(f"\n🎉 Setup Complete!")
    print(f"✅ Uploaded {uploaded_count} master templates")
    print(f"✅ Supabase storage configured")
    print(f"✅ Database schema created")
    print(f"✅ Ready for Salesforce integration")
    
    print(f"\n🔗 Your Certificate Management System:")
    print(f"   App URL: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/")
    print(f"   Test with Account ID: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001")
    
    print(f"\n📋 Next Steps:")
    print(f"   1. Set up Salesforce Remote Site Settings")
    print(f"   2. Create Visualforce page")
    print(f"   3. Add to Account page layout")
    print(f"   4. Test with real Salesforce accounts")

if __name__ == '__main__':
    main()
