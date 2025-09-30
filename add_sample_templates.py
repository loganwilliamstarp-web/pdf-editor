#!/usr/bin/env python3

import os
import psycopg2
import uuid
import json

# Database connection
DATABASE_URL = os.environ.get("DATABASE_URL")

def add_sample_templates():
    """Add sample templates to the database"""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        return

    try:
        print("Connecting to database...")
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()

        # Sample templates to add
        sample_templates = [
            {
                'id': str(uuid.uuid4()),
                'template_name': 'ACORD 25 - Certificate of Liability Insurance',
                'template_type': 'liability_insurance',
                'storage_path': 'demo_templates/acord_25.pdf',
                'file_size': 0,
                'form_fields': json.dumps({
                    'company_name': '',
                    'policy_number': '',
                    'effective_date': '',
                    'expiration_date': '',
                    'insured_name': '',
                    'address': ''
                })
            },
            {
                'id': str(uuid.uuid4()),
                'template_name': 'ACORD 125 - Certificate of Liability Insurance (Short Form)',
                'template_type': 'liability_insurance',
                'storage_path': 'demo_templates/acord_125.pdf',
                'file_size': 0,
                'form_fields': json.dumps({
                    'company_name': '',
                    'policy_number': '',
                    'effective_date': '',
                    'expiration_date': '',
                    'insured_name': '',
                    'address': '',
                    'liability_limit': ''
                })
            },
            {
                'id': str(uuid.uuid4()),
                'template_name': 'ACORD 130 - Evidence of Commercial Property Insurance',
                'template_type': 'property_insurance',
                'storage_path': 'demo_templates/acord_130.pdf',
                'file_size': 0,
                'form_fields': json.dumps({
                    'company_name': '',
                    'policy_number': '',
                    'effective_date': '',
                    'expiration_date': '',
                    'insured_name': '',
                    'property_address': ''
                })
            },
            {
                'id': str(uuid.uuid4()),
                'template_name': 'ACORD 140 - Evidence of Commercial Property Insurance (Broad Form)',
                'template_type': 'property_insurance',
                'storage_path': 'demo_templates/acord_140.pdf',
                'file_size': 0,
                'form_fields': json.dumps({
                    'company_name': '',
                    'policy_number': '',
                    'effective_date': '',
                    'expiration_date': '',
                    'insured_name': '',
                    'property_address': '',
                    'coverage_type': ''
                })
            },
            {
                'id': str(uuid.uuid4()),
                'template_name': 'ACORD 27 - Evidence of Property Insurance',
                'template_type': 'property_insurance',
                'storage_path': 'demo_templates/acord_27.pdf',
                'file_size': 0,
                'form_fields': json.dumps({
                    'company_name': '',
                    'policy_number': '',
                    'effective_date': '',
                    'expiration_date': '',
                    'insured_name': '',
                    'property_address': ''
                })
            }
        ]

        print(f"Adding {len(sample_templates)} sample templates...")

        for template in sample_templates:
            file_name = Path(template['storage_path']).name
            candidates = [
                Path('database/templates') / file_name,
                Path('database/templates') / file_name.replace('acord_', 'acord'),
                Path(template['storage_path'])
            ]
            pdf_blob = None
            for candidate in candidates:
                if candidate.exists():
                    pdf_blob = candidate.read_bytes()
                    template['file_size'] = len(pdf_blob)
                    template['storage_path'] = f"db://sample/{file_name}"
                    break

            if not pdf_blob:
                pdf_blob = None

            try:
                cur.execute('''
                    INSERT INTO master_templates (id, template_name, template_type, storage_path, file_size, pdf_blob, form_fields)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                ''', (
                    template['id'],
                    template['template_name'],
                    template['template_type'],
                    template['storage_path'],
                    template['file_size'],
                    Binary(pdf_blob) if pdf_blob else None,
                    template['form_fields']
                ))
                print(f"Added template: {template['template_name']}")
            except Exception as e:
                print(f"Error adding template {template['template_name']}: {e}")

        conn.commit()

        # Verify templates were added
        cur.execute('SELECT COUNT(*) FROM master_templates')
        count = cur.fetchone()[0]
        print(f"\nTotal templates in database: {count}")

        cur.close()
        conn.close()
        print("Sample templates added successfully!")

    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    add_sample_templates()
