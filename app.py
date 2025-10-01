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
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("Warning: PyMuPDF not available. PDF pre-filling will be limited.")


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
        
        # Ensure pdf_blob column exists (migration for existing databases)
        try:
            cur.execute('SELECT pdf_blob FROM master_templates LIMIT 1;')
        except psycopg2.errors.UndefinedColumn:
            print("Adding missing pdf_blob column to master_templates...")
            cur.execute('ALTER TABLE master_templates ADD COLUMN pdf_blob BYTEA;')
            conn.commit()
            print("Successfully added pdf_blob column")
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


@app.route('/api/pdf/template/<template_id>/<account_id>')
def serve_pdf_template_with_fields(template_id, account_id):
    """Serve PDF template with account-specific field values filled in"""
    print(f"=== PDF TEMPLATE REQUESTED ===")
    print(f"Template ID: {template_id}")
    print(f"Account ID: {account_id}")
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get template and account-specific data
        try:
            cur.execute('''
                SELECT
                    mt.template_name, mt.template_type, mt.storage_path, mt.file_size, mt.pdf_blob, mt.form_fields,
                    td.field_values
                FROM master_templates mt
                LEFT JOIN template_data td
                    ON td.template_id = mt.id AND td.account_id = %s
                WHERE mt.id = %s
            ''', (account_id, template_id))
        except psycopg2.errors.UndefinedColumn:
            # Fallback if pdf_blob column doesn't exist
            conn.rollback()
            cur.execute('''
                SELECT
                    mt.template_name, mt.template_type, mt.storage_path, mt.file_size, NULL::BYTEA AS pdf_blob, mt.form_fields,
                    td.field_values
                FROM master_templates mt
                LEFT JOIN template_data td
                    ON td.template_id = mt.id AND td.account_id = %s
                WHERE mt.id = %s
            ''', (account_id, template_id))
        
        result = cur.fetchone()
        if not result:
            return jsonify({'error': 'Template not found'}), 404
        
        template_name = result.get('template_name')
        template_type = (result.get('template_type') or '').lower()
        storage_path = result.get('storage_path') or ''
        pdf_blob = result.get('pdf_blob')
        form_fields_payload = coerce_form_fields_payload(result.get('form_fields'))
        field_values_raw = result.get('field_values') or {}
        
        # Parse field_values if it's a JSON string
        if isinstance(field_values_raw, str):
            try:
                field_values = json.loads(field_values_raw)
            except json.JSONDecodeError:
                field_values = {}
        else:
            field_values = field_values_raw or {}

        print(f"Serving PDF template with fields: {template_name} (ID: {template_id}, Account: {account_id})")
        print(f"Field values retrieved: {len(field_values)} fields")
        if field_values:
            non_empty_fields = {k: v for k, v in field_values.items() if v and str(v).strip()}
            print(f"Non-empty field values: {len(non_empty_fields)}")
            if non_empty_fields:
                print(f"Sample non-empty fields: {list(non_empty_fields.items())[:3]}")
        else:
            print("No field values found in database")

        # Get PDF content
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

        # If no field values saved, create initial template data for this account
        if not field_values:
            print("No field values found, creating initial template data for account")
            print("Field values type:", type(field_values), "Content:", field_values)
            
            # Create initial template_data record with empty field values
            try:
                cur.execute('''
                    INSERT INTO template_data (account_id, template_id, field_values)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (account_id, template_id) DO NOTHING
                ''', (account_id, template_id, json.dumps({})))
                conn.commit()
                print(f"Created initial template data for account {account_id}")
            except Exception as init_error:
                print(f"Warning: Could not create initial template data: {init_error}")
                conn.rollback()
            
            # Return original template
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
        
        # Pre-fill PDF with saved field values using PyMuPDF (fitz)
        print(f"=== STARTING PDF PRE-FILLING ===")
        print(f"PYMUPDF_AVAILABLE: {PYMUPDF_AVAILABLE}")
        print(f"Field values count: {len(field_values)}")
        print(f"Field values type: {type(field_values)}")
        
        try:
            if PYMUPDF_AVAILABLE and field_values:
                print(f"Filling PDF with {len(field_values)} field values using PyMuPDF")
                
                # Load PDF with PyMuPDF
                pdf_doc = fitz.open(stream=pdf_content, filetype="pdf")
                
                # DEBUG: Check actual field types in your PDF
                print("\n=== PDF FIELD TYPES DEBUG ===")
                checkbox_fields = []
                for page in pdf_doc:
                    for widget in page.widgets():
                        if 'checkbox' in widget.field_type_string.lower() or widget.field_type_string == 'CheckBox':
                            checkbox_fields.append({
                                'name': widget.field_name,
                                'type': widget.field_type_string,
                                'current_value': widget.field_value,
                                'saved_value': field_values.get(widget.field_name, 'NOT_FOUND')
                            })
                        print(f"Field: {widget.field_name}")
                        print(f"  Type: {widget.field_type}")
                        print(f"  Type String: {widget.field_type_string}")
                        print(f"  Current Value: {widget.field_value}")
                print("=== END DEBUG ===\n")
                
                # DEBUG: Check for X-style checkboxes specifically
                print("\n=== CHECKING FOR X-STYLE CHECKBOXES ===")
                page = pdf_doc[0]
                all_widgets = list(page.widgets())
                print(f"Total widgets on page: {len(all_widgets)}")

                # Look for the specific checkboxes from ACORD forms
                checkbox_names = [
                    'COMMERCIAL GENERAL LIABILITY',
                    'CLAIMS-MADE',
                    'OCCUR',
                    'COVERAGE',
                    'CLAIMS',
                    'OCCURRENCE'
                ]

                for widget in all_widgets:
                    field_name = widget.field_name
                    # Check if this might be one of those X checkboxes
                    if any(name.replace(' ', '').replace('-', '').lower() in field_name.lower().replace('_', '') 
                           for name in checkbox_names):
                        print(f"\n=== X-STYLE CHECKBOX ===")
                        print(f"Field name: {widget.field_name}")
                        print(f"Field type: {widget.field_type}")
                        print(f"Field type string: {widget.field_type_string}")
                        print(f"Field value: {widget.field_value}")
                        print(f"Field flags: {widget.field_flags}")
                        
                        # Check if it's actually a button
                        if hasattr(widget, 'button_states'):
                            print(f"Button states: {widget.button_states}")
                        if hasattr(widget, 'field_states'):
                            print(f"Field states: {widget.field_states}")
                        
                        print(f"Widget rect: {widget.rect}")
                        print(f"=========================\n")
                
                print("=== END X-STYLE CHECKBOX DEBUG ===\n")
                
                if checkbox_fields:
                    print("=== CHECKBOX FIELDS FOUND ===")
                    for cb in checkbox_fields:
                        print(f"Checkbox: {cb['name']}")
                        print(f"  Type: {cb['type']}")
                        print(f"  Current Value: {cb['current_value']}")
                        print(f"  Saved Value: {cb['saved_value']}")
                        # Check if this checkbox should be filled
                        if cb['saved_value'] != 'NOT_FOUND':
                            is_checked = cb['saved_value'] in [True, 'true', 'True', '1', 'Yes', 'yes', 'On', '/1']
                            print(f"  Should be filled: {is_checked}")
                    print("=== END CHECKBOX DEBUG ===\n")
                
                filled_count = 0
                failed_fields = []
                
                # Iterate through all pages (ACORD forms can have multiple pages)
                for page_num in range(len(pdf_doc)):
                    page = pdf_doc[page_num]
                    
                    # Get all widgets on this page
                    for widget in page.widgets():
                        field_name = widget.field_name
                        
                        # Check if we have a saved value for this field
                        if field_name in field_values:
                            saved_value = field_values[field_name]
                            
                            # Handle empty values - PyMuPDF needs explicit empty strings
                            if saved_value is None or saved_value == '':
                                saved_value = ''
                            
                            try:
                                field_type = widget.field_type_string
                                
                                if field_type == 'Text':
                                    widget.field_value = str(saved_value)
                                    widget.update()
                                    filled_count += 1
                                    if saved_value:  # Only log non-empty
                                        print(f"Filled text field '{field_name}': '{saved_value}'")
                                
                                elif field_type == 'CheckBox':
                                    # Handle ACORD checkbox values like /Yes, /Off, /1
                                    print(f"Processing checkbox '{field_name}': saved_value='{saved_value}'")
                                    
                                    # Determine if checkbox should be checked based on ACORD values
                                    is_checked = saved_value in [True, 'true', 'True', '1', 'Yes', 'yes', 'On', '/1', '/Yes', '/On']
                                    is_unchecked = saved_value in [False, 'false', 'False', '0', 'No', 'no', 'Off', '/Off', '/No']
                                    
                                    print(f"  is_checked={is_checked}, is_unchecked={is_unchecked}")
                                    
                                    try:
                                        # For ACORD forms, use the exact saved value to preserve appearance
                                        if saved_value and not is_unchecked:
                                            # Use the exact value from database (e.g., '/Yes', '/1')
                                            widget.field_value = saved_value
                                            print(f"  Set checkbox to exact value: '{saved_value}'")
                                        elif is_unchecked:
                                            # Use the exact unchecked value (e.g., '/Off')
                                            widget.field_value = saved_value
                                            print(f"  Set checkbox to exact unchecked value: '{saved_value}'")
                                        else:
                                            # Fallback to boolean
                                            widget.field_value = is_checked
                                            print(f"  Set checkbox to boolean: {is_checked}")
                                        
                                        # Don't call update() to preserve original appearance
                                        # widget.update()  # Commented out to preserve styling
                                        
                                        filled_count += 1
                                        print(f"Checkbox '{field_name}': SUCCESS (value: '{saved_value}')")
                                        
                                    except Exception as checkbox_error:
                                        print(f"Checkbox setting failed for '{field_name}': {checkbox_error}")
                                        # Fallback: try with update
                                        try:
                                            widget.field_value = saved_value if saved_value else is_checked
                                            widget.update()
                                            filled_count += 1
                                            print(f"Checkbox '{field_name}': SUCCESS with update (value: '{saved_value}')")
                                        except Exception as fallback_error:
                                            print(f"Checkbox fallback failed: {fallback_error}")
                                            failed_fields.append((field_name, f"Checkbox error: {fallback_error}"))
                                
                                elif field_type in ['Button', 'Btn']:
                                    # These X-style checkboxes are buttons, not checkboxes
                                    print(f"Processing button field '{field_name}': saved_value='{saved_value}'")
                                    
                                    # Handle ACORD button values like /Yes, /Off, /1
                                    is_checked = saved_value in [True, 'true', 'True', '1', 'Yes', 'yes', 'On', 'X', '/1', '/Yes', '/On']
                                    is_unchecked = saved_value in [False, 'false', 'False', '0', 'No', 'no', 'Off', '/Off', '/No']
                                    
                                    print(f"  is_checked={is_checked}, is_unchecked={is_unchecked}")
                                    
                                    try:
                                        # For ACORD forms, use the exact saved value to preserve appearance
                                        if saved_value and not is_unchecked:
                                            # Use the exact value from database (e.g., '/Yes', '/1')
                                            widget.field_value = saved_value
                                            print(f"  Set button to exact value: '{saved_value}'")
                                        elif is_unchecked:
                                            # Use the exact unchecked value (e.g., '/Off')
                                            widget.field_value = saved_value
                                            print(f"  Set button to exact unchecked value: '{saved_value}'")
                                        else:
                                            # Fallback
                                            widget.field_value = 'X' if is_checked else 'Off'
                                            print(f"  Set button to fallback state: {'X' if is_checked else 'Off'}")
                                        
                                        # Don't call update() to preserve original appearance
                                        # widget.update()  # Commented out to preserve styling
                                        
                                        filled_count += 1
                                        print(f"Button '{field_name}': SUCCESS (value: '{saved_value}')")
                                        
                                    except Exception as button_error:
                                        print(f"Button setting failed for '{field_name}': {button_error}")
                                        # Fallback: try with update
                                        try:
                                            widget.field_value = saved_value if saved_value else ('X' if is_checked else 'Off')
                                            widget.update()
                                            filled_count += 1
                                            print(f"Button '{field_name}': SUCCESS with update (value: '{saved_value}')")
                                        except Exception as fallback_error:
                                            print(f"Button fallback failed: {fallback_error}")
                                            failed_fields.append((field_name, f"Button error: {fallback_error}"))
                                
                                elif field_type == 'RadioButton':
                                    # X-style boxes might be radio buttons
                                    is_checked = saved_value in [True, 'true', 'True', '1', 'Yes', 'yes', 'On', 'X']
                                    
                                    print(f"Processing radio button '{field_name}': saved_value='{saved_value}', is_checked={is_checked}")
                                    
                                    if is_checked:
                                        # Try common ACORD radio values
                                        for state in ['X', 'Yes', '1', 'On']:
                                            try:
                                                widget.field_value = state
                                                widget.update()
                                                filled_count += 1
                                                print(f"Radio button {field_name} set to: {state} - SUCCESS")
                                                break
                                            except Exception as radio_error:
                                                print(f"Radio button {field_name} failed with state {state}: {radio_error}")
                                                continue
                                    else:
                                        # For unchecked radio buttons
                                        try:
                                            widget.field_value = 'Off'
                                            widget.update()
                                            filled_count += 1
                                            print(f"Radio button {field_name} set to: Off - SUCCESS")
                                        except Exception as radio_error:
                                            print(f"Radio button {field_name} failed to set to Off: {radio_error}")
                                            failed_fields.append((field_name, f"Radio button error: {radio_error}"))
                                
                            except Exception as field_error:
                                failed_fields.append((field_name, str(field_error)))
                                print(f"Failed to fill '{field_name}': {field_error}")
                
                print(f"=== PRE-FILL COMPLETE ===")
                print(f"Successfully filled: {filled_count} fields")
                print(f"Failed fields: {len(failed_fields)}")
                if failed_fields:
                    print(f"Failures: {failed_fields[:5]}")  # Show first 5
                
                # Save the filled PDF
                filled_pdf_content = pdf_doc.write()
                pdf_doc.close()
                
                from flask import Response
                return Response(
                    filled_pdf_content,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': f'inline; filename="{template_name}_filled.pdf"',
                        'Access-Control-Allow-Origin': '*',
                        'Cache-Control': 'no-cache'
                    }
                )
            else:
                if not PYMUPDF_AVAILABLE:
                    print("PyMuPDF not available, returning original template")
                if not field_values:
                    print("No field values to fill, returning original template")
                
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
                
        except Exception as fill_error:
            print(f"Error filling PDF fields: {fill_error}")
            # Return original template if filling fails
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
        print(f"Error serving PDF template with fields: {e}")
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

@app.route('/api/debug/pdf-content', methods=['POST'])
def debug_pdf_content():
    """Debug endpoint to inspect PDF content being sent"""
    try:
        data = request.get_json()
        pdf_content = data.get('pdf_content')
        
        if not pdf_content:
            return jsonify({'error': 'No PDF content provided'}), 400
        
        # Decode base64 PDF content
        if pdf_content.startswith('data:application/pdf;base64,'):
            pdf_content = pdf_content.split(',')[1]
        
        try:
            pdf_bytes = base64.b64decode(pdf_content)
            print(f"PDF content size: {len(pdf_bytes)} bytes")
            
            # Try to extract fields using pypdf
            if PYPDF_AVAILABLE:
                pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
                print(f"PDF pages: {len(pdf_reader.pages)}")
                
                # Try get_fields() method
                fields_dict = pdf_reader.get_fields()
                if fields_dict:
                    print(f"Found {len(fields_dict)} fields using get_fields()")
                    field_info = []
                    for field_name, field_obj in list(fields_dict.items())[:5]:
                        field_value = ''
                        if hasattr(field_obj, 'get') and field_obj.get('/V'):
                            field_value = str(field_obj.get('/V'))
                        elif hasattr(field_obj, 'get') and field_obj.get('/AS'):
                            field_value = str(field_obj.get('/AS'))
                        field_info.append({
                            'name': field_name,
                            'value': field_value,
                            'type': str(field_obj.get('/FT', 'unknown'))
                        })
                    
                    return jsonify({
                        'success': True,
                        'pdf_size': len(pdf_bytes),
                        'pages': len(pdf_reader.pages),
                        'fields_found': len(fields_dict),
                        'sample_fields': field_info
                    })
                else:
                    return jsonify({
                        'success': True,
                        'pdf_size': len(pdf_bytes),
                        'pages': len(pdf_reader.pages),
                        'fields_found': 0,
                        'message': 'No fields found using get_fields()'
                    })
            else:
                return jsonify({'error': 'pypdf not available'}), 500
                
        except Exception as e:
            return jsonify({'error': f'PDF processing error: {str(e)}'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug/test', methods=['GET'])
def debug_test():
    """Simple test endpoint to verify server is running latest code"""
    return jsonify({
        'message': 'Debug test endpoint working',
        'timestamp': '2024-01-01 16:01:00',
        'version': 'latest'
    })

@app.route('/api/pdf/field-values/<template_id>/<account_id>')
def get_pdf_field_values(template_id, account_id):
    """Get saved field values for client-side PDF pre-filling"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get saved field values from template_data table
        cur.execute('''
            SELECT field_values FROM template_data 
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, template_id))
        
        result = cur.fetchone()
        if result and result.get('field_values'):
            field_values = result.get('field_values')
            if isinstance(field_values, str):
                try:
                    field_values = json.loads(field_values)
                except json.JSONDecodeError:
                    field_values = {}
        else:
            field_values = {}
        
        return jsonify({
            'success': True,
            'template_id': template_id,
            'account_id': account_id,
            'field_values': field_values,
            'field_count': len(field_values),
            'non_empty_count': len({k: v for k, v in field_values.items() if v and str(v).strip()})
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

@app.route('/api/debug/pymupdf-test/<template_id>/<account_id>')
def debug_pymupdf_test(template_id, account_id):
    """Debug endpoint to test PyMuPDF pre-filling directly"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get template and field values
        try:
            cur.execute('''
                SELECT
                    mt.template_name, mt.template_type, mt.storage_path, mt.file_size, mt.pdf_blob, mt.form_fields,
                    td.field_values
                FROM master_templates mt
                LEFT JOIN template_data td
                    ON td.template_id = mt.id AND td.account_id = %s
                WHERE mt.id = %s
            ''', (account_id, template_id))
        except psycopg2.errors.UndefinedColumn:
            conn.rollback()
            cur.execute('''
                SELECT
                    mt.template_name, mt.template_type, mt.storage_path, mt.file_size, NULL::BYTEA AS pdf_blob, mt.form_fields,
                    td.field_values
                FROM master_templates mt
                LEFT JOIN template_data td
                    ON td.template_id = mt.id AND td.account_id = %s
                WHERE mt.id = %s
            ''', (account_id, template_id))
        
        result = cur.fetchone()
        if not result:
            return jsonify({'error': 'Template not found'}), 404
        
        field_values_raw = result.get('field_values') or {}
        
        # Parse field_values if it's a JSON string
        if isinstance(field_values_raw, str):
            try:
                field_values = json.loads(field_values_raw)
            except json.JSONDecodeError:
                field_values = {}
        else:
            field_values = field_values_raw or {}
        
        # Get PDF content
        pdf_content = None
        pdf_blob = result.get('pdf_blob')
        if pdf_blob:
            try:
                pdf_content = bytes(pdf_blob)
            except (TypeError, ValueError):
                pdf_content = pdf_blob
        
        if not pdf_content:
            local_file = resolve_local_template_file(result.get('template_type', '').lower(), result.get('storage_path', ''))
            if local_file:
                pdf_content = local_file.read_bytes()
        
        if not pdf_content:
            return jsonify({'error': 'No PDF content available'}), 404
        
        # Test PyMuPDF pre-filling
        debug_info = {
            'template_id': template_id,
            'account_id': account_id,
            'template_name': result.get('template_name'),
            'field_values_count': len(field_values),
            'non_empty_count': len({k: v for k, v in field_values.items() if v and str(v).strip()}),
            'pymupdf_available': PYMUPDF_AVAILABLE,
            'pdf_size': len(pdf_content),
            'test_results': {}
        }
        
        if PYMUPDF_AVAILABLE:
            try:
                # Load PDF with PyMuPDF
                pdf_doc = fitz.open(stream=pdf_content, filetype="pdf")
                
                # Get all form fields
                form_fields = list(pdf_doc[0].widgets())  # Convert generator to list
                debug_info['test_results']['form_fields_found'] = len(form_fields)
                debug_info['test_results']['form_field_names'] = [widget.field_name for widget in form_fields[:10]]  # First 10
                
                filled_count = 0
                failed_fields = []
                
                # Test filling a few fields
                test_fields = list(field_values.items())[:5]  # Test first 5 fields
                for field_name, saved_value in test_fields:
                    if not saved_value or str(saved_value).strip() == '':
                        continue
                        
                    field_found = False
                    for widget in form_fields:
                        if widget.field_name == field_name:
                            field_found = True
                            field_type = widget.field_type_string
                            
                            try:
                                if field_type == 'text':
                                    widget.field_value = str(saved_value)
                                    widget.update()
                                    filled_count += 1
                                elif field_type == 'checkbox':
                                    widget.field_value = True if saved_value in [True, 'true', '1', 'Yes'] else False
                                    widget.update()
                                    filled_count += 1
                                elif field_type == 'radiobutton':
                                    widget.field_value = str(saved_value)
                                    widget.update()
                                    filled_count += 1
                                    
                                debug_info['test_results'][f'field_{field_name}'] = {
                                    'type': field_type,
                                    'value': saved_value,
                                    'status': 'filled'
                                }
                            except Exception as e:
                                debug_info['test_results'][f'field_{field_name}'] = {
                                    'type': field_type,
                                    'value': saved_value,
                                    'status': 'error',
                                    'error': str(e)
                                }
                                failed_fields.append(field_name)
                            break
                    
                    if not field_found:
                        debug_info['test_results'][f'field_{field_name}'] = {
                            'value': saved_value,
                            'status': 'not_found'
                        }
                        failed_fields.append(field_name)
                
                debug_info['test_results']['filled_count'] = filled_count
                debug_info['test_results']['failed_fields'] = failed_fields
                
                # Save the filled PDF
                filled_pdf_content = pdf_doc.write()
                pdf_doc.close()
                
                debug_info['test_results']['filled_pdf_size'] = len(filled_pdf_content)
                debug_info['test_results']['success'] = True
                
            except Exception as e:
                debug_info['test_results']['error'] = str(e)
                debug_info['test_results']['success'] = False
        else:
            debug_info['test_results']['error'] = 'PyMuPDF not available'
            debug_info['test_results']['success'] = False
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

@app.route('/api/debug/pdf-prefill/<template_id>/<account_id>')
def debug_pdf_prefill(template_id, account_id):
    """Debug endpoint to test PDF pre-filling logic"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get template and account-specific data (same query as PDF template function)
        try:
            cur.execute('''
                SELECT
                    mt.template_name, mt.template_type, mt.storage_path, mt.file_size, mt.pdf_blob, mt.form_fields,
                    td.field_values
                FROM master_templates mt
                LEFT JOIN template_data td
                    ON td.template_id = mt.id AND td.account_id = %s
                WHERE mt.id = %s
            ''', (account_id, template_id))
        except psycopg2.errors.UndefinedColumn:
            conn.rollback()
            cur.execute('''
                SELECT
                    mt.template_name, mt.template_type, mt.storage_path, mt.file_size, NULL::BYTEA AS pdf_blob, mt.form_fields,
                    td.field_values
                FROM master_templates mt
                LEFT JOIN template_data td
                    ON td.template_id = mt.id AND td.account_id = %s
                WHERE mt.id = %s
            ''', (account_id, template_id))
        
        result = cur.fetchone()
        if not result:
            return jsonify({'error': 'Template not found'}), 404
        
        field_values_raw = result.get('field_values') or {}
        
        # Parse field_values if it's a JSON string
        if isinstance(field_values_raw, str):
            try:
                field_values = json.loads(field_values_raw)
            except json.JSONDecodeError:
                field_values = {}
        else:
            field_values = field_values_raw or {}
        
        non_empty_fields = {k: v for k, v in field_values.items() if v and str(v).strip()}
        
        return jsonify({
            'template_id': template_id,
            'account_id': account_id,
            'template_name': result.get('template_name'),
            'field_values_type': type(field_values_raw).__name__,
            'field_values_raw_preview': str(field_values_raw)[:200] + '...' if len(str(field_values_raw)) > 200 else str(field_values_raw),
            'parsed_field_count': len(field_values),
            'non_empty_count': len(non_empty_fields),
            'non_empty_fields': list(non_empty_fields.items())[:5],
            'success': True
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

@app.route('/api/debug/database', methods=['GET'])
def debug_database():
    """Debug endpoint to check database contents"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Check template_data table
        cur.execute('''
            SELECT account_id, template_id, field_values, updated_at 
            FROM template_data 
            WHERE account_id = '001qr00000umdmiian' 
            ORDER BY updated_at DESC 
            LIMIT 5
        ''')
        results = cur.fetchall()
        
        debug_info = {
            'template_data_records': len(results),
            'recent_records': []
        }
        
        for row in results:
            field_values = row.get('field_values') or {}
            non_empty = {k: v for k, v in field_values.items() if v and str(v).strip()}
            debug_info['recent_records'].append({
                'account_id': row.get('account_id'),
                'template_id': row.get('template_id'),
                'field_count': len(field_values),
                'non_empty_count': len(non_empty),
                'updated_at': str(row.get('updated_at')),
                'sample_fields': list(field_values.items())[:3] if field_values else [],
                'non_empty_fields': list(non_empty.items()) if non_empty else []
            })
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

@app.route('/api/pdf/save-fields', methods=['POST'])
def save_pdf_fields():
    """Save PDF field values to database with automatic field extraction from PDF content."""
    print("=== SAVE PDF FIELDS CALLED ===")
    print(f"Request method: {request.method}")
    print(f"Request content type: {request.content_type}")
    try:
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify({'success': False, 'error': 'Invalid JSON payload'}), 400

        template_id = data.get('template_id')
        account_id = data.get('account_id')
        field_values = data.get('field_values', {})
        pdf_content = data.get('pdf_content')  # Base64 encoded PDF content
        form_fields_payload = None

        if 'form_fields' in data:
            form_fields_payload = enrich_form_fields_payload(data.get('form_fields'), method='adobe_embed_api')

        if not template_id or not account_id:
            return jsonify({'success': False, 'error': 'Missing template_id or account_id'}), 400

        conn = get_db()
        cur = conn.cursor()

        # If PDF content is provided, extract fields from it
        extracted_fields = {}
        if pdf_content:
            try:
                # Decode base64 PDF content
                if pdf_content.startswith('data:application/pdf;base64,'):
                    pdf_content = pdf_content.split(',')[1]
                pdf_bytes = base64.b64decode(pdf_content)
                
                # Extract fields using pypdf
                if PYPDF_AVAILABLE:
                    pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
                    print(f"PDF reader created, pages: {len(pdf_reader.pages)}")
                    
                    # Try multiple extraction methods
                    try:
                        # Method 1: Use get_fields() method
                        fields_dict = pdf_reader.get_fields()
                        if fields_dict:
                            print(f"Found {len(fields_dict)} fields using get_fields()")
                            for field_name, field_obj in fields_dict.items():
                                field_value = ''
                                if hasattr(field_obj, 'get') and field_obj.get('/V'):
                                    field_value = str(field_obj.get('/V'))
                                elif hasattr(field_obj, 'get') and field_obj.get('/AS'):
                                    field_value = str(field_obj.get('/AS'))
                                extracted_fields[field_name] = field_value
                        else:
                            print("No fields found using get_fields()")
                    except Exception as e:
                        print(f"get_fields() failed: {e}")
                    
                    # Method 2: Manual AcroForm extraction
                    if not extracted_fields:
                        try:
                            root = pdf_reader.trailer['/Root']
                            print(f"PDF root keys: {list(root.keys()) if hasattr(root, 'keys') else 'No keys'}")
                            
                            if '/AcroForm' in root:
                                acro_form = root['/AcroForm']
                                print(f"AcroForm found, keys: {list(acro_form.keys()) if hasattr(acro_form, 'keys') else 'No keys'}")
                                
                                if '/Fields' in acro_form:
                                    fields = acro_form['/Fields']
                                    print(f"Found {len(fields)} field objects")
                                    
                                    for i, field in enumerate(fields):
                                        try:
                                            field_obj = field.get_object()
                                            if '/T' in field_obj:  # Field name
                                                field_name = str(field_obj['/T'])
                                                field_value = ''
                                                if '/V' in field_obj:  # Field value
                                                    field_value = str(field_obj['/V'])
                                                elif '/AS' in field_obj:  # Appearance state (for checkboxes)
                                                    field_value = str(field_obj['/AS'])
                                                extracted_fields[field_name] = field_value
                                                print(f"Field {i+1}: {field_name} = '{field_value}'")
                                        except Exception as field_error:
                                            print(f"Error processing field {i}: {field_error}")
                            else:
                                print("No /AcroForm found in PDF root")
                        except Exception as e:
                            print(f"Manual AcroForm extraction failed: {e}")
                    
                    print(f"Final extracted {len(extracted_fields)} fields from PDF content")
                    
                    # Debug: Show sample of extracted fields
                    if extracted_fields:
                        sample_fields = list(extracted_fields.items())[:5]
                        print(f"Sample extracted fields: {sample_fields}")
                        non_empty_fields = {k: v for k, v in extracted_fields.items() if v and str(v).strip()}
                        print(f"Non-empty fields count: {len(non_empty_fields)}")
                        if non_empty_fields:
                            sample_non_empty = list(non_empty_fields.items())[:3]
                            print(f"Sample non-empty fields: {sample_non_empty}")
                        else:
                            print("WARNING: All extracted fields are empty strings!")
                            # Show first 10 fields with their exact values
                            first_10 = list(extracted_fields.items())[:10]
                            print(f"First 10 extracted fields: {first_10}")
                            # Check for any non-empty values
                            any_non_empty = any(v and str(v).strip() for v in extracted_fields.values())
                            print(f"Any non-empty values found: {any_non_empty}")
                    
                    # Use extracted fields if they have values, otherwise use provided field_values
                    if extracted_fields:
                        # Merge extracted fields with provided field_values (extracted takes precedence)
                        final_field_values = {**field_values, **extracted_fields}
                    else:
                        final_field_values = field_values
                else:
                    print("pypdf not available, using provided field values")
                    final_field_values = field_values
                    
            except Exception as extract_error:
                print(f"Error extracting fields from PDF: {extract_error}")
                final_field_values = field_values
        else:
            final_field_values = field_values

        # Check if template data already exists for this account
        cur.execute('''
            SELECT id FROM template_data 
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, template_id))

        existing_data = cur.fetchone()

        print("Saving field values for template {0}, account {1}: {2} fields".format(template_id, account_id, len(final_field_values)))
        if final_field_values:
            print("Field sample:", list(final_field_values.items())[:5])
            non_empty_saved = {k: v for k, v in final_field_values.items() if v and str(v).strip()}
            print(f"Non-empty fields being saved: {len(non_empty_saved)}")
            if non_empty_saved:
                print("Non-empty field sample:", list(non_empty_saved.items())[:3])
        else:
            print("WARNING: No field values to save!")

        if existing_data:
            print(f"Updating existing template_data record for account {account_id}, template {template_id}")
            cur.execute('''
                UPDATE template_data 
                SET field_values = %s, updated_at = NOW(), version = version + 1
                WHERE account_id = %s AND template_id = %s
            ''', (json.dumps(final_field_values), account_id, template_id))
            print(f"UPDATE query executed, affected rows: {cur.rowcount}")
        else:
            print(f"Inserting new template_data record for account {account_id}, template {template_id}")
            cur.execute('''
                INSERT INTO template_data (account_id, template_id, field_values)
                VALUES (%s, %s, %s)
            ''', (account_id, template_id, json.dumps(final_field_values)))
            print(f"INSERT query executed, affected rows: {cur.rowcount}")

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
        print(f"Database commit successful for account {account_id}, template {template_id}")

        # Verify the data was actually saved by querying it back
        cur.execute('''
            SELECT field_values FROM template_data 
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, template_id))
        verification_result = cur.fetchone()
        if verification_result:
            saved_field_values = verification_result.get('field_values') or {}
            print(f"Verification: {len(saved_field_values)} field values saved to database")
            if saved_field_values:
                non_empty_saved = {k: v for k, v in saved_field_values.items() if v and str(v).strip()}
                print(f"Verification: {len(non_empty_saved)} non-empty field values in database")
                if non_empty_saved:
                    print(f"Verification sample: {list(non_empty_saved.items())[:3]}")
        else:
            print("WARNING: Verification query returned no results - data may not have been saved!")

        return jsonify({
            'success': True,
            'message': 'Field values saved successfully',
            'template_id': template_id,
            'account_id': account_id,
            'field_count': len(final_field_values),
            'extracted_fields_count': len(extracted_fields),
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
        
        print(f"Retrieved field_values_raw: {type(field_values_raw)}, length: {len(field_values_payload) if isinstance(field_values_payload, dict) else 'N/A'}")
        print(f"Raw field_values content: {str(field_values_raw)[:200]}...")
        if field_values_payload and isinstance(field_values_payload, dict):
            non_empty_loaded = {k: v for k, v in field_values_payload.items() if v and str(v).strip()}
            print(f"Non-empty fields loaded: {len(non_empty_loaded)}")
            if non_empty_loaded:
                print("Non-empty field sample:", list(non_empty_loaded.items())[:3])
            else:
                print("All loaded field values are empty strings")
        else:
            print("No field values payload or not a dictionary")

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
