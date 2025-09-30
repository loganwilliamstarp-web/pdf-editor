from flask import Flask, jsonify, request, send_from_directory, render_template
from flask_cors import CORS
import os
import io
import uuid
import json
from pathlib import Path
from datetime import datetime

# Optional imports with fallbacks

LOCAL_TEMPLATE_DIR = Path(__file__).resolve().parent / "database" / "templates"
LOCAL_TEMPLATE_FILES = {
    "acord25": "acord25.pdf",
    "acord27": "acord27.pdf",
    "acord28": "acord28.pdf",
    "acord30": "acord30.pdf",
    "acord35": "acord35.pdf",
    "acord36": "acord36.pdf",
    "acord37": "acord37.pdf",
    "acord125": "acord125.pdf",
    "acord126": "acord126.pdf",
    "acord130": "acord130.pdf",
    "acord140": "acord140.pdf",
}

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    print("Warning: Supabase not available. PDF storage will be limited.")
    SUPABASE_AVAILABLE = False

try:
    from pypdf import PdfReader, PdfWriter
    PYPDF_AVAILABLE = True
except ImportError:
    print("Warning: pypdf not available. PDF field extraction will be limited.")
    PYPDF_AVAILABLE = False

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    PSYCOPG2_AVAILABLE = True
    print("✅ psycopg2 available for database operations")
except ImportError:
    print("Warning: psycopg2 not available. Database functionality will be limited.")
    PSYCOPG2_AVAILABLE = False

app = Flask(__name__, static_folder='frontend/build', static_url_path='')
CORS(app)

# Initialize Supabase (for storage only) - with better error handling
supabase = None
if SUPABASE_AVAILABLE:
    try:
        supabase_url = os.environ.get('SUPABASE_URL')
        supabase_key = os.environ.get('SUPABASE_KEY')
        
        if supabase_url and supabase_key:
            supabase = create_client(supabase_url, supabase_key)
            print("âœ… Supabase client initialized successfully")
        else:
            print("Warning: Supabase credentials not found. Storage functionality will be limited.")
    except Exception as e:
        print(f"Warning: Failed to initialize Supabase client: {e}")
        supabase = None

# Connect to Heroku PostgreSQL
def get_db():
    if not PSYCOPG2_AVAILABLE:
        raise Exception("psycopg2 not available. Database functionality disabled.")

    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise Exception("DATABASE_URL environment variable not set")

    return psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor,
        sslmode='require'
    )

def setup_supabase_storage():
    """Setup Supabase storage using default bucket"""
    try:
        if not supabase:
            return False
        
        # Try to list existing buckets to verify connection
        try:
            buckets = supabase.storage.list_buckets()
            print(f"✅ Connected to Supabase storage. Available buckets: {[b.name for b in buckets]}")
            
            # Use the first available bucket or default to 'files'
            if buckets:
                bucket_name = buckets[0].name
            else:
                bucket_name = 'files'
            
            print(f"✅ Using Supabase bucket: {bucket_name}")
            return True
            
        except Exception as e:
            print(f"⚠️  Could not list buckets, but Supabase client is available: {e}")
            # Even if we can't list buckets, the client might still work
            return True
            
    except Exception as e:
        print(f"❌ Supabase storage setup error: {e}")
        return False

def create_database_schema():
    """Create the complete database schema"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Enable UUID extension
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
        
        # Master Templates Table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS master_templates (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                template_name VARCHAR(100) NOT NULL UNIQUE,
                template_type VARCHAR(50) NOT NULL,
                storage_path VARCHAR(500),
                file_size INTEGER,
                pdf_blob BYTEA,
                form_fields JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        ''')
        cur.execute('ALTER TABLE master_templates ADD COLUMN IF NOT EXISTS pdf_blob BYTEA;')
        cur.execute('ALTER TABLE master_templates ALTER COLUMN storage_path DROP NOT NULL;')
        
        # Template Data by Account
        cur.execute('''
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
        ''')
        
        # Generated Certificates
        cur.execute('''
            CREATE TABLE IF NOT EXISTS generated_certificates (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                account_id VARCHAR(18) NOT NULL,
                template_id UUID REFERENCES master_templates(id),
                certificate_name VARCHAR(255),
                storage_path VARCHAR(500),
                status VARCHAR(50) DEFAULT 'draft',
                generated_at TIMESTAMP DEFAULT NOW()
            );
        ''')
        
        # Certificate Holders
        cur.execute('''
            CREATE TABLE IF NOT EXISTS certificate_holders (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                account_id VARCHAR(18) NOT NULL,
                name VARCHAR(255),
                email VARCHAR(255),
                address TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        ''')
        
        # Create indexes
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_generated_certificates_account ON generated_certificates(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_certificate_holders_account ON certificate_holders(account_id);')
        
        conn.commit()
        cur.close()
        conn.close()
        print("âœ… Database schema created successfully")
        return True
        
    except Exception as e:
        print(f"Database schema creation error: {e}")
        return False

@app.route("/")
def serve_app():
    try:
        return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        return f"<h1>Certificate Management System</h1><p>Frontend not available: {str(e)}</p>"

@app.route("/<account_id>")
def serve_account(account_id):
    """Serve the app for a specific Salesforce Account ID"""
    try:
        # Check if this is a Salesforce Account ID (15 or 18 characters starting with 001)
        if len(account_id) >= 15 and account_id.startswith('001'):
            try:
                # Try to serve from static folder first
                return send_from_directory(app.static_folder, 'index.html')
            except Exception:
                try:
                    # Fallback to root directory
                    return send_from_directory('.', 'index.html')
                except Exception as e:
                    return f"""
                    <!DOCTYPE html>
                    <html>
                    <head><title>Certificate Management System</title></head>
                    <body>
                        <h1>Certificate Management System</h1>
                        <p>Account: {account_id}</p>
                        <p>Error: {str(e)}</p>
                        <p><a href="/api/health">Check API Health</a></p>
                    </body>
                    </html>
                    """
        else:
            return f"Invalid Account ID format: {account_id}", 400
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route("/<path:path>")
def serve_static(path):
    """Serve static files"""
    try:
        return send_from_directory(app.static_folder, path)
    except Exception as e:
        return f"File not found: {path}", 404

@app.route("/api/health")
def health():
    return jsonify({
        "status": "healthy", 
        "message": "Certificate Management System is working",
        "timestamp": datetime.utcnow().isoformat(),
        "features": {
            "supabase": SUPABASE_AVAILABLE and supabase is not None,
            "pypdf": PYPDF_AVAILABLE,
            "database": PSYCOPG2_AVAILABLE
        }
    })

@app.route("/api/setup", methods=['POST'])
def setup_system():
    """Initialize Supabase storage and database schema"""
    try:
        # Check if this is a SQL execution request
        if request.is_json and request.json.get('action') == 'create_tables':
            sql = request.json.get('sql')
            if sql:
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(sql)
                    conn.commit()
                    cur.close()
                    conn.close()
                    return jsonify({'success': True, 'message': 'SQL executed successfully'})
                except Exception as e:
                    return jsonify({'success': False, 'error': f'SQL execution failed: {str(e)}'}), 500
        
        # Original setup functionality
        results = {}
        
        # Setup Supabase storage
        if SUPABASE_AVAILABLE and supabase:
            storage_result = setup_supabase_storage()
            results['supabase_storage'] = storage_result
        else:
            results['supabase_storage'] = False
        
        # Setup database schema
        if PSYCOPG2_AVAILABLE:
            db_result = create_database_schema()
            results['database_schema'] = db_result
        else:
            results['database_schema'] = False
        
        return jsonify({
            'success': True,
            'message': 'System setup completed',
            'results': results
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/account/<account_id>")
def get_account_info(account_id):
    """Get account information for the given Salesforce Account ID"""
    return jsonify({
        "account_id": account_id,
        "message": "Account data will be integrated with Salesforce",
        "status": "ready"
    })


@app.route("/pdf-editor/<template_id>")
def pdf_editor(template_id):
    """Serve the interactive PDF editor popup."""
    account_id = (request.args.get('account_id') or '').strip()
    if not account_id:
        account_id = '001000000000001'
    else:
        account_id = account_id[:18]

    template_name = "PDF Template"

    if PSYCOPG2_AVAILABLE:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                'SELECT template_name FROM master_templates WHERE id = %s',
                (template_id,)
            )
            row = cur.fetchone()
            if row:
                if isinstance(row, dict):
                    template_name = row.get('template_name') or template_name
                else:
                    template_name = row[0] if row and row[0] else template_name
        except Exception as db_error:
            print(f"Warning: unable to load template metadata for editor: {db_error}")
        finally:
            if 'conn' in locals():
                cur.close()
                conn.close()

    return render_template(
        'pdf_editor.html',
        template_id=template_id,
        account_id=account_id,
        template_name=template_name
    )

@app.route("/api/account/<account_id>/templates", methods=['GET'])
def get_account_templates(account_id):
    """Get all master templates available for the account"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT id, template_name, template_type, form_fields, created_at
            FROM master_templates
            ORDER BY template_name
        ''')
        
        templates = cur.fetchall()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'account_id': account_id,
            'templates': [dict(row) for row in templates]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/provision-pdf", methods=['POST'])
def provision_pdf():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        pdf_file = request.files['file']
        name = request.form.get('name', 'Untitled Certificate')
        account_id = request.form.get('account_id')
        
        if not account_id:
            return jsonify({'success': False, 'error': 'Account ID is required'}), 400
        
        # For now, just return success without actually processing
        return jsonify({
            'success': True,
            'certificate_id': 'temp-id-123',
            'message': 'PDF uploaded successfully (demo mode)',
            'metadata': {
                'name': name,
                'account_id': account_id,
                'filename': pdf_file.filename
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/upload-template", methods=['POST'])
def upload_template():
    """Upload a master template and persist it in Postgres (Supabase optional)."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        pdf_file = request.files['file']
        template_name = request.form.get('name', 'Untitled Template')
        template_type = request.form.get('template_type', 'general')
        account_id = request.form.get('account_id', 'system')

        template_id = str(uuid.uuid4())
        pdf_data = pdf_file.read()
        if not pdf_data:
            return jsonify({'success': False, 'error': 'Uploaded file is empty'}), 400

        storage_path = f'db://master_templates/{template_id}.pdf'

        if supabase:
            try:
                bucket_names = ['certificates', 'files', 'templates', 'default']
                for bucket_name in bucket_names:
                    try:
                        supabase.storage.from_(bucket_name).upload(
                            storage_path,
                            pdf_data,
                            {'content-type': 'application/pdf', 'upsert': 'true'}
                        )
                        print(f"Uploaded template to Supabase bucket {bucket_name}")
                        break
                    except Exception as exc:
                        print(f"Supabase upload to {bucket_name} failed: {exc}")
            except Exception as supabase_error:
                print(f"Supabase upload skipped due to error: {supabase_error}")

        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute('''
                INSERT INTO master_templates (id, template_name, template_type, storage_path, file_size, pdf_blob, form_fields)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            ''', (
                template_id,
                template_name,
                template_type,
                storage_path,
                len(pdf_data),
                psycopg2.Binary(pdf_data),
                Json({})
            ))

            result = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            return jsonify({
                'success': True,
                'template_id': template_id,
                'message': 'Template uploaded successfully',
                'metadata': {
                    'name': template_name,
                    'type': template_type,
                    'storage_path': storage_path,
                    'file_size': len(pdf_data)
                }
            })

        except Exception as db_error:
            if 'conn' in locals() and conn:
                conn.rollback()
            return jsonify({'success': False, 'error': f'Database save failed: {str(db_error)}'}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/upload-template-simple", methods=['POST'])
def upload_template_simple():
    """Simple template upload that stores the PDF in Postgres."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        pdf_file = request.files['file']
        template_name = request.form.get('name', 'Untitled Template')
        template_type = request.form.get('template_type', 'general')
        account_id = request.form.get('account_id', 'system')

        template_id = str(uuid.uuid4())
        pdf_data = pdf_file.read()
        if not pdf_data:
            return jsonify({'success': False, 'error': 'Uploaded file is empty'}), 400

        storage_path = f'db://master_templates/{template_id}.pdf'

        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute('''
                INSERT INTO master_templates (id, template_name, template_type, storage_path, file_size, pdf_blob, form_fields)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            ''', (
                template_id,
                template_name,
                template_type,
                storage_path,
                len(pdf_data),
                psycopg2.Binary(pdf_data),
                Json({})
            ))

            result = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            return jsonify({
                'success': True,
                'template_id': template_id,
                'message': 'Template saved successfully',
                'metadata': {
                    'name': template_name,
                    'type': template_type,
                    'storage_path': storage_path,
                    'file_size': len(pdf_data)
                }
            })

        except Exception as db_error:
            if 'conn' in locals() and conn:
                conn.rollback()
            return jsonify({'success': False, 'error': f'Database save failed: {str(db_error)}'}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def resolve_local_template_file(template_type, storage_path):
    """Resolve a local PDF template file path if available."""
    candidates = []

    if storage_path:
        storage_path = storage_path.strip()
        if storage_path:
            candidate = Path(storage_path)
            candidates.append(candidate)
            candidates.append(Path(__file__).resolve().parent / storage_path)
            normalized_name = candidate.stem.replace('acord_', 'acord').replace('_', '').lower()
            if normalized_name:
                candidates.append(LOCAL_TEMPLATE_DIR / f"{normalized_name}.pdf")
            candidates.append(LOCAL_TEMPLATE_DIR / candidate.name)

    if template_type:
        template_type = template_type.lower()
        mapped = LOCAL_TEMPLATE_FILES.get(template_type)
        if mapped:
            candidates.append(LOCAL_TEMPLATE_DIR / mapped)

    for candidate in candidates:
        try:
            if candidate and candidate.exists():
                return candidate
        except TypeError:
            continue

    return None

@app.route('/api/pdf/template/<template_id>')
def serve_pdf_template(template_id):
    """Serve PDF template file for Adobe Embed API"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get template from database
        cur.execute('SELECT template_name, template_type, storage_path, file_size, pdf_blob, form_fields FROM master_templates WHERE id = %s', (template_id,))
        template = cur.fetchone()
        
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        
        template_name = template.get('template_name')
        template_type = (template.get('template_type') or '').lower()
        storage_path = template.get('storage_path') or ''
        pdf_blob = template.get('pdf_blob')
        form_fields_raw = template.get('form_fields')

        form_fields_data = {}
        if form_fields_raw:
            if isinstance(form_fields_raw, dict):
                form_fields_data = form_fields_raw
            else:
                try:
                    form_fields_data = json.loads(form_fields_raw) if form_fields_raw else {}
                except (TypeError, ValueError):
                    form_fields_data = {}

        print(f"Serving PDF template: {template_name} (ID: {template_id})")

        pdf_content = None
        if pdf_blob:
            try:
                pdf_content = bytes(pdf_blob)
            except (TypeError, ValueError):
                pdf_content = pdf_blob

        if not pdf_content:
            local_file = resolve_local_template_file(template_type, storage_path)
            if local_file:
                pdf_content = local_file.read_bytes()

        if not pdf_content:
            # Fallback to generated PDF if no stored asset is available
            pdf_content = create_pdf_with_form_fields(template_name, form_fields_data)
        
        from flask import Response
        return Response(
            pdf_content,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'inline; filename="{template_name}.pdf"',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache'
            }
        )
        
    except Exception as e:
        print(f"Error serving PDF template: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

def create_pdf_with_form_fields(template_name, form_fields_data):
    """Create a PDF with form fields based on template type"""
    
    # Define common ACORD form fields based on template name
    acord_fields = {
        'ACORD 25': [
            {'name': 'company_name', 'label': 'Company Name', 'x': 100, 'y': 700},
            {'name': 'policy_number', 'label': 'Policy Number', 'x': 400, 'y': 700},
            {'name': 'effective_date', 'label': 'Effective Date', 'x': 100, 'y': 650},
            {'name': 'expiration_date', 'label': 'Expiration Date', 'x': 400, 'y': 650},
            {'name': 'insured_name', 'label': 'Insured Name', 'x': 100, 'y': 600},
            {'name': 'address', 'label': 'Address', 'x': 100, 'y': 550},
        ],
        'ACORD 125': [
            {'name': 'company_name', 'label': 'Company Name', 'x': 100, 'y': 700},
            {'name': 'policy_number', 'label': 'Policy Number', 'x': 400, 'y': 700},
            {'name': 'effective_date', 'label': 'Effective Date', 'x': 100, 'y': 650},
            {'name': 'expiration_date', 'label': 'Expiration Date', 'x': 400, 'y': 650},
            {'name': 'insured_name', 'label': 'Insured Name', 'x': 100, 'y': 600},
            {'name': 'address', 'label': 'Address', 'x': 100, 'y': 550},
            {'name': 'liability_limit', 'label': 'Liability Limit', 'x': 100, 'y': 500},
        ],
        'ACORD 126': [
            {'name': 'company_name', 'label': 'Company Name', 'x': 100, 'y': 700},
            {'name': 'policy_number', 'label': 'Policy Number', 'x': 400, 'y': 700},
            {'name': 'effective_date', 'label': 'Effective Date', 'x': 100, 'y': 650},
            {'name': 'expiration_date', 'label': 'Expiration Date', 'x': 400, 'y': 650},
            {'name': 'insured_name', 'label': 'Insured Name', 'x': 100, 'y': 600},
            {'name': 'address', 'label': 'Address', 'x': 100, 'y': 550},
            {'name': 'liability_limit', 'label': 'Liability Limit', 'x': 100, 'y': 500},
            {'name': 'additional_insured', 'label': 'Additional Insured', 'x': 100, 'y': 450},
        ],
        'ACORD 130': [
            {'name': 'company_name', 'label': 'Company Name', 'x': 100, 'y': 700},
            {'name': 'policy_number', 'label': 'Policy Number', 'x': 400, 'y': 700},
            {'name': 'effective_date', 'label': 'Effective Date', 'x': 100, 'y': 650},
            {'name': 'expiration_date', 'label': 'Expiration Date', 'x': 400, 'y': 650},
            {'name': 'insured_name', 'label': 'Insured Name', 'x': 100, 'y': 600},
            {'name': 'property_address', 'label': 'Property Address', 'x': 100, 'y': 550},
        ]
    }
    
    # Get fields for this template type
    fields = acord_fields.get(template_name, acord_fields['ACORD 25'])  # Default to ACORD 25
    
    # Create a PDF with form fields
    pdf_content = create_simple_pdf_with_fields(template_name, fields)
    
    return pdf_content

def create_simple_pdf_with_fields(template_name, fields):
    """Create a simple PDF with form fields using a working PDF structure"""
    
    # Create a simple working PDF with form fields
    # This creates a valid PDF that Adobe PDF Embed can load and edit
    
    pdf_content = f"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
/AcroForm <<
/Fields ["""
    
    # Add field references
    for i in range(len(fields)):
        pdf_content += f"{10 + i} 0 R "
    
    pdf_content += """]
/NeedAppearances true
>>
>>
endobj

2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj

3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
/Annots ["""
    
    # Add annotation references
    for i in range(len(fields)):
        pdf_content += f"{20 + i} 0 R "
    
    pdf_content += """]
>>
endobj

4 0 obj
<<
/Length 300
>>
stream
BT
/F1 18 Tf
100 750 Td
({template_name}) Tj
0 -40 Td
/F1 12 Tf
(Certificate Management System) Tj
0 -60 Td
/F1 10 Tf
(Form Fields - Click to edit) Tj
ET
endstream
endobj"""
    
    # Add form field objects
    for i, field in enumerate(fields):
        field_num = 10 + i
        annot_num = 20 + i
        y_pos = 650 - (i * 30)  # Space fields vertically
        
        pdf_content += f"""

{field_num} 0 obj
<<
/Type /Annot
/Subtype /Widget
/Rect [100 {y_pos} 450 {y_pos + 20}]
/FT /Tx
/T ({field['name']})
/V ()
/DA (/Helv 10 Tf 0 g)
/F 4
/BS <<
/W 1
/S /S
>>
>>
endobj

{annot_num} 0 obj
<<
/Type /Annot
/Subtype /Widget
/Rect [100 {y_pos} 450 {y_pos + 20}]
/FT /Tx
/T ({field['name']})
/V ()
/DA (/Helv 10 Tf 0 g)
/F 4
/BS <<
/W 1
/S /S
>>
>>
endobj"""
    
    pdf_content += """

xref
0 30"""
    
    # Add xref entries (simplified)
    for i in range(30):
        pdf_content += f"\n0000000000 00000 n "
    
    pdf_content += """

trailer
<<
/Size 30
/Root 1 0 R
>>
startxref
2000
%%EOF"""
    
    return pdf_content.encode('utf-8')

@app.route('/api/pdf/render/<template_id>')
def render_pdf(template_id):
    """Render PDF template for editing (legacy endpoint)"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get template from database
        cur.execute('SELECT template_name, storage_path FROM master_templates WHERE id = %s', (template_id,))
        template = cur.fetchone()
        
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        
        template_name, storage_path = template
        
        return jsonify({
            'success': True,
            'template_name': template_name,
            'pdf_url': f'/api/pdf/template/{template_id}'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

@app.route('/api/pdf/save-fields', methods=['POST'])
def save_pdf_fields():
    """Save PDF field values to database"""
    try:
        data = request.get_json()
        template_id = data.get('template_id')
        account_id = data.get('account_id')
        field_values = data.get('field_values', {})
        
        if not template_id or not account_id:
            return jsonify({'success': False, 'error': 'Missing template_id or account_id'}), 400
        
        conn = get_db()
        cur = conn.cursor()
        
        # Check if template data already exists for this account
        cur.execute('''
            SELECT id FROM template_data 
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, template_id))
        
        existing_data = cur.fetchone()
        
        if existing_data:
            # Update existing data
            cur.execute('''
                UPDATE template_data 
                SET field_values = %s, updated_at = NOW(), version = version + 1
                WHERE account_id = %s AND template_id = %s
            ''', (json.dumps(field_values), account_id, template_id))
        else:
            # Insert new data
            cur.execute('''
                INSERT INTO template_data (account_id, template_id, field_values)
                VALUES (%s, %s, %s)
            ''', (account_id, template_id, json.dumps(field_values)))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Field values saved successfully',
            'template_id': template_id,
            'account_id': account_id,
            'field_count': len(field_values)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

@app.route('/api/pdf/get-fields/<template_id>/<account_id>')
def get_pdf_fields(template_id, account_id):
    """Get saved PDF field values for a template and account"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT field_values FROM template_data 
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, template_id))
        
        data = cur.fetchone()
        
        if data:
            return jsonify({
                'success': True,
                'field_values': json.loads(data[0]) if data[0] else {}
            })
        else:
            return jsonify({
                'success': True,
                'field_values': {}
            })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
