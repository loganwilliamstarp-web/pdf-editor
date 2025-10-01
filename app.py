from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import io
import uuid
import json
from pathlib import Path
from datetime import datetime
import base64

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

# Form field helpers


def extract_form_fields_from_pdf_bytes(pdf_bytes):
    """Extract AcroForm field metadata from PDF bytes."""
    if not PYPDF_AVAILABLE or not pdf_bytes:
        return []

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        field_map = reader.get_fields() or {}
        fields = []

        for name, data in field_map.items():
            if not name:
                continue

            field_type = str(data.get('/FT', '')).strip('/') or 'text'
            flags = int(data.get('/Ff', 0))
            options = []
            if '/Opt' in data:
                opt_values = data.get('/Opt') or []
                if isinstance(opt_values, (list, tuple)):
                    for entry in opt_values:
                        options.append(str(entry))
                else:
                    options.append(str(opt_values))

            if '/V' in data and data.get('/V') is not None:
                default_value = str(data.get('/V'))
            else:
                default_value = None

            rect = None
            raw_rect = data.get('/Rect')
            if isinstance(raw_rect, (list, tuple)) and len(raw_rect) == 4:
                try:
                    rect = [float(coord) for coord in raw_rect]
                except (TypeError, ValueError):
                    rect = None

            fields.append({
                'name': str(name),
                'type': field_type or 'text',
                'label': str(data.get('/TU') or data.get('/T') or name),
                'required': bool(flags & 2),
                'default_value': default_value,
                'flags': flags,
                'options': options,
                'rect': rect,
            })

        return fields
    except Exception as exc:
        print(f"Warning: unable to extract form fields automatically ({exc})")
        return []


def coerce_form_fields_payload(raw):
    """Normalize stored form field data into a dictionary with a fields list."""
    if raw in (None, ''):
        payload = {}
    elif isinstance(raw, dict):
        payload = dict(raw)
    elif isinstance(raw, list):
        payload = {'fields': raw}
    else:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            payload = parsed
        elif isinstance(parsed, list):
            payload = {'fields': parsed}
        else:
            payload = {}

    fields = payload.get('fields')
    if isinstance(fields, list):
        payload['fields'] = [field for field in fields if isinstance(field, dict)]
    else:
        payload['fields'] = []

    extraction = payload.get('extraction')
    if isinstance(extraction, dict):
        payload['extraction'] = dict(extraction)
    elif 'extraction' in payload:
        payload.pop('extraction', None)

    return payload


def enrich_form_fields_payload(payload, method=None):
    """Attach extraction metadata to a normalized form field payload."""
    normalized = coerce_form_fields_payload(payload)
    extraction = normalized.get('extraction')
    if not isinstance(extraction, dict):
        extraction = {}

    extraction['field_count'] = len(normalized['fields'])
    extraction['updated_at'] = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    if method:
        extraction['method'] = method

    normalized['extraction'] = extraction
    return normalized

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

        template_payloads = []
        for row in templates:
            template_data = dict(row)
            template_data['form_fields'] = coerce_form_fields_payload(template_data.get('form_fields'))
            template_payloads.append(template_data)

        return jsonify({
            'success': True,
            'account_id': account_id,
            'templates': template_payloads
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
        try:
            cur.execute('SELECT template_name, template_type, storage_path, file_size, pdf_blob, form_fields FROM master_templates WHERE id = %s', (template_id,))
        except psycopg2.errors.UndefinedColumn:
            conn.rollback()
            cur.execute('SELECT template_name, template_type, storage_path, file_size, NULL::BYTEA AS pdf_blob, form_fields FROM master_templates WHERE id = %s', (template_id,))
        template = cur.fetchone()
        
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        
        template_name = template.get('template_name')
        template_type = (template.get('template_type') or '').lower()
        storage_path = template.get('storage_path') or ''
        pdf_blob = template.get('pdf_blob')
        form_fields_payload = coerce_form_fields_payload(template.get('form_fields'))

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
            pdf_content = create_pdf_with_form_fields(template_name, form_fields_payload)

        # Attempt to extract and persist form field metadata if missing
        if not form_fields_payload.get('fields') and pdf_content:
            extracted_fields = extract_form_fields_from_pdf_bytes(pdf_content)
            if extracted_fields:
                try:
                    form_fields_payload = enrich_form_fields_payload({'fields': extracted_fields}, method='pypdf-auto')
                    cur.execute(
                        'UPDATE master_templates SET form_fields = %s, updated_at = NOW() WHERE id = %s',
                        (Json(form_fields_payload), template_id)
                    )
                    conn.commit()
                    print(f"Extracted and stored {len(extracted_fields)} form fields for template {template_id}")
                except Exception as extraction_store_error:
                    print(f"Warning: unable to store extracted form fields ({extraction_store_error})")
                    conn.rollback()

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

def create_pdf_with_form_fields(template_name, form_fields_payload):
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
    """Save PDF field values to database and optionally update template metadata."""
    try:
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify({'success': False, 'error': 'Invalid JSON payload'}), 400

        template_id = data.get('template_id')
        account_id = data.get('account_id')
        field_values = data.get('field_values', {})
        form_fields_payload = None

        if 'form_fields' in data:
            form_fields_payload = enrich_form_fields_payload(data.get('form_fields'), method='adobe_embed_api')

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

        print("Saving field values for template {0}, account {1}: {2} fields".format(template_id, account_id, len(field_values)))
        if field_values:
            print("Field sample:", list(field_values.items())[:5])

        if existing_data:
            cur.execute('''
                UPDATE template_data 
                SET field_values = %s, updated_at = NOW(), version = version + 1
                WHERE account_id = %s AND template_id = %s
            ''', (json.dumps(field_values), account_id, template_id))
        else:
            cur.execute('''
                INSERT INTO template_data (account_id, template_id, field_values)
                VALUES (%s, %s, %s)
            ''', (account_id, template_id, json.dumps(field_values)))

        template_fields_updated = False
        if form_fields_payload is not None:
            cur.execute('SELECT form_fields FROM master_templates WHERE id = %s', (template_id,))
            template_row = cur.fetchone()
            existing_fields = coerce_form_fields_payload(template_row.get('form_fields')) if template_row else {'fields': []}
            if existing_fields != form_fields_payload:
                cur.execute(
                    'UPDATE master_templates SET form_fields = %s, updated_at = NOW() WHERE id = %s',
                    (Json(form_fields_payload), template_id)
                )
                template_fields_updated = True

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Field values saved successfully',
            'template_id': template_id,
            'account_id': account_id,
            'field_count': len(field_values),
            'form_fields_updated': template_fields_updated,
            'form_fields': form_fields_payload['fields'] if form_fields_payload else None
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()


@app.route('/api/extract-fields', methods=['POST'])
def extract_pdf_fields():
    """Extract field values from PDF blob using pypdf"""
    try:
        # Handle both FormData (from save callback) and JSON (from polling)
        if request.files and 'pdf' in request.files:
            # FormData from save callback
            pdf_file = request.files['pdf']
            pdf_bytes = pdf_file.read()
        elif request.get_json() and 'pdf_content' in request.get_json():
            # JSON from polling (legacy)
            data = request.get_json()
            pdf_content = data['pdf_content']
            if pdf_content.startswith('data:application/pdf;base64,'):
                pdf_content = pdf_content.split(',')[1]
            pdf_bytes = base64.b64decode(pdf_content)
        else:
            return jsonify({'success': False, 'error': 'No PDF content provided'}), 400
        
        if not PYPDF_AVAILABLE:
            return jsonify({'success': False, 'error': 'pypdf not available'}), 500
        
        # Extract field values using pypdf
        pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
        form_data = {}
        
        if '/AcroForm' in pdf_reader.trailer['/Root']:
            acro_form = pdf_reader.trailer['/Root']['/AcroForm']
            if '/Fields' in acro_form:
                fields = acro_form['/Fields']
                for field in fields:
                    field_obj = field.get_object()
                    if '/T' in field_obj:  # Field name
                        field_name = field_obj['/T']
                        field_value = ''
                        
                        if '/V' in field_obj:  # Field value
                            field_value = str(field_obj['/V'])
                        elif '/AS' in field_obj:  # Appearance state (for checkboxes)
                            field_value = str(field_obj['/AS'])
                        
                        form_data[field_name] = field_value
        
        return jsonify({
            'success': True,
            'form_data': form_data,
            'field_count': len(form_data)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pdf/get-fields/<template_id>/<account_id>')
def get_pdf_fields(template_id, account_id):
    """Get saved PDF field values for a template and account"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute('''
            SELECT
                td.field_values,
                mt.form_fields
            FROM master_templates mt
            LEFT JOIN template_data td
                ON td.template_id = mt.id AND td.account_id = %s
            WHERE mt.id = %s
        ''', (account_id, template_id))

        data = cur.fetchone()

        if not data:
            return jsonify({'success': False, 'error': 'Template not found'}), 404

        if isinstance(data, dict):
            field_values_raw = data.get('field_values')
            form_fields_raw = data.get('form_fields')
        else:
            field_values_raw = data[0] if len(data) > 0 else None
            form_fields_raw = data[1] if len(data) > 1 else None

        if isinstance(field_values_raw, str):
            try:
                field_values_payload = json.loads(field_values_raw) if field_values_raw else {}
            except (TypeError, ValueError):
                field_values_payload = {}
        elif field_values_raw is None:
            field_values_payload = {}
        else:
            field_values_payload = field_values_raw

        form_fields_payload = coerce_form_fields_payload(form_fields_raw)

        return jsonify({
            'success': True,
            'template_id': template_id,
            'account_id': account_id,
            'field_values': field_values_payload,
            'form_fields': form_fields_payload['fields'],
            'form_field_metadata': form_fields_payload
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
