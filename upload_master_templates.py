"""
ACORD master template uploader without Supabase.
Loads PDF files from the local database/templates directory and stores them
in Postgres so they can be reused across all Salesforce accounts.
"""

import os
import io
from pathlib import Path

import psycopg2
from psycopg2 import Binary
from psycopg2.extras import Json

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False
    print("Warning: pypdf not available. Form field metadata will be empty.")

TEMPLATES_DIR = Path('database/templates')
TEMPLATE_MAPPING = {
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
    'acord140.pdf': ('ACORD 140 - Evidence of Commercial Property Insurance', 'acord140'),
}


def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print('Missing DATABASE_URL environment variable')
        return None

    return psycopg2.connect(database_url, sslmode='require')


def create_database_schema():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return False

        cur = conn.cursor()
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
        cur.execute("""
            CREATE TABLE IF NOT EXISTS master_templates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                template_name VARCHAR(100) NOT NULL UNIQUE,
                template_type VARCHAR(50) NOT NULL,
                storage_path VARCHAR(500),
                file_size INTEGER,
                pdf_blob BYTEA,
                form_fields JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute('ALTER TABLE master_templates ADD COLUMN IF NOT EXISTS pdf_blob BYTEA;')
        cur.execute('ALTER TABLE master_templates ALTER COLUMN storage_path DROP NOT NULL;')

        cur.execute("""
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
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS generated_certificates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                account_id VARCHAR(18) NOT NULL,
                template_id UUID REFERENCES master_templates(id),
                certificate_name VARCHAR(255),
                storage_path VARCHAR(500),
                status VARCHAR(50) DEFAULT 'draft',
                generated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute("""
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
        """)

        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);')

        conn.commit()
        return True
    except Exception as exc:
        print(f'Error creating database schema: {exc}')
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            cur.close()
            conn.close()


def extract_form_fields(pdf_bytes):
    if not PYPDF_AVAILABLE:
        return []

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        fields = []
        field_map = reader.get_fields() or {}
        for name, data in field_map.items():
            fields.append({
                'name': name,
                'type': str(data.get('/FT', 'text')),
                'value': str(data.get('/V', '')),
                'required': bool(data.get('/Ff', 0) & 2)
            })
        return fields
    except Exception as exc:
        print(f'Warning: unable to extract form fields ({exc})')
        return []


def upload_master_template(file_path, template_name, template_type):
    if not file_path.exists():
        print(f'File not found: {file_path}')
        return None

    pdf_bytes = file_path.read_bytes()
    form_fields = extract_form_fields(pdf_bytes)

    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None

        cur = conn.cursor()
        storage_path = f'db://master_templates/{template_type}.pdf'
        cur.execute("""
            INSERT INTO master_templates (template_name, template_type, storage_path, file_size, pdf_blob, form_fields)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (template_name) DO UPDATE SET
                storage_path = EXCLUDED.storage_path,
                file_size = EXCLUDED.file_size,
                pdf_blob = EXCLUDED.pdf_blob,
                form_fields = EXCLUDED.form_fields,
                updated_at = NOW()
            RETURNING id
        """, (
            template_name,
            template_type,
            storage_path,
            len(pdf_bytes),
            Binary(pdf_bytes),
            Json(form_fields)
        ))

        template_id = cur.fetchone()[0]
        conn.commit()
        return template_id
    except Exception as exc:
        print(f'Error uploading master template {template_name}: {exc}')
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            cur.close()
            conn.close()


def main():
    print('ACORD Master Template Upload Script (Postgres storage)')
    print('=' * 60)

    if not os.environ.get('DATABASE_URL'):
        print('DATABASE_URL environment variable not set')
        return

    if not create_database_schema():
        print('Failed to ensure database schema')
        return

    if not TEMPLATES_DIR.exists():
        print(f'Templates directory not found: {TEMPLATES_DIR.resolve()}')
        return

    uploaded = 0
    for filename, (template_name, template_type) in TEMPLATE_MAPPING.items():
        file_path = TEMPLATES_DIR / filename
        if not file_path.exists():
            print(f'Skipping missing template file: {filename}')
            continue

        print(f'Uploading {template_name} from {file_path}...')
        result = upload_master_template(file_path, template_name, template_type)
        if result:
            uploaded += 1
            print(f'  -> Stored as template_id {result}')
        else:
            print('  -> Upload failed')

    print('\nUpload complete: {} templates stored in Postgres.'.format(uploaded))
    print('Each account can now reuse these master templates without Supabase.')


if __name__ == '__main__':
    main()
