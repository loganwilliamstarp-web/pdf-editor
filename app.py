from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import io
import uuid
import json
from pathlib import Path
from datetime import datetime
import base64
import re

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

US_STATE_CHOICES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

US_STATE_CODES = set(US_STATE_CHOICES.keys())
US_STATE_OPTIONS = [
    {'code': code, 'name': name} for code, name in sorted(US_STATE_CHOICES.items(), key=lambda item: item[1])
]
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ACCOUNT_ID_REGEX = re.compile(r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$")

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    print("Warning: Supabase not available. PDF storage will be limited.")
    SUPABASE_AVAILABLE = False

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, BooleanObject
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
                name VARCHAR(255) NOT NULL,
                master_remarks TEXT,
                address_line1 VARCHAR(255),
                address_line2 VARCHAR(255),
                city VARCHAR(120),
                state VARCHAR(2),
                postal_code VARCHAR(20),
                email VARCHAR(255),
                phone VARCHAR(50),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                address TEXT
            );
        ''')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS master_remarks TEXT;')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(255);')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS address_line2 VARCHAR(255);')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS city VARCHAR(120);')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS state VARCHAR(2);')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20);')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS phone VARCHAR(50);')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS email VARCHAR(255);')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS address TEXT;')
        cur.execute('ALTER TABLE certificate_holders ALTER COLUMN name SET NOT NULL;')
        cur.execute('UPDATE certificate_holders SET address_line1 = COALESCE(address_line1, address) WHERE address IS NOT NULL AND (address_line1 IS NULL OR address_line1 = \'\');')
        cur.execute('UPDATE certificate_holders SET updated_at = COALESCE(updated_at, created_at, NOW());')
        cur.execute('ALTER TABLE certificate_holders ALTER COLUMN updated_at SET DEFAULT NOW();')
        
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

def normalize_string(value, max_length=None):
    """Normalize incoming string data."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    value = str(value).strip()
    if not value:
        return None
    if max_length:
        return value[:max_length]
    return value


def normalize_account_id(account_id):
    """Validate and normalize a Salesforce Account ID."""
    normalized = normalize_string(account_id)
    if not normalized:
        raise ValueError("Account ID is required.")

    length = len(normalized)
    if length not in (15, 18):
        raise ValueError("Account ID must be 15 or 18 characters.")
    if length == 15:
        normalized = normalized.upper()
    if length == 18:
        normalized = normalized[:18]
    if not ACCOUNT_ID_REGEX.match(normalized):
        raise ValueError("Account ID must be alphanumeric.")

    return normalized


def serialize_timestamp(value):
    """Return ISO formatted timestamp when possible."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def sanitize_certificate_holder_payload(raw_data, existing=None, account_id=None):
    """Validate and normalize certificate holder payload."""
    existing = existing or {}
    errors = []
    payload = {}

    if not isinstance(raw_data, dict):
        raw_data = {}

    normalized_existing_account = None
    if existing.get('account_id'):
        try:
            normalized_existing_account = normalize_account_id(existing.get('account_id'))
        except ValueError:
            normalized_existing_account = existing.get('account_id')

    if account_id is not None:
        try:
            account_id = normalize_account_id(account_id)
        except ValueError as exc:
            errors.append(str(exc))
            account_id = None

    provided_account_id = raw_data.get('account_id')
    if provided_account_id is not None:
        try:
            normalized_provided = normalize_account_id(provided_account_id)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if account_id and normalized_provided != account_id:
                errors.append("Account ID mismatch for certificate holder payload.")
            elif normalized_existing_account and normalized_provided != normalized_existing_account:
                errors.append("Account ID mismatch for certificate holder payload.")
            else:
                account_id = normalized_provided
    elif normalized_existing_account:
        account_id = normalized_existing_account

    name_source = raw_data.get('name')
    if name_source is None and existing:
        name_source = existing.get('name')
    name = normalize_string(name_source, 255)
    if not name:
        errors.append("Name is required.")
    payload['name'] = name

    master_remarks_source = raw_data.get('master_remarks', existing.get('master_remarks') if existing else None)
    payload['master_remarks'] = normalize_string(master_remarks_source)

    address_line1_source = raw_data.get('address_line1', existing.get('address_line1') if existing else None)
    payload['address_line1'] = normalize_string(address_line1_source, 255)

    city_source = raw_data.get('city', existing.get('city') if existing else None)
    payload['city'] = normalize_string(city_source, 120)

    state_source = raw_data.get('state')
    if state_source is None and existing:
        state_source = existing.get('state')
    state = normalize_string(state_source, 2)
    if state:
        state = state.upper()
        if state not in US_STATE_CODES:
            errors.append("State must be a valid U.S. state code.")
    payload['state'] = state

    email_source = raw_data.get('email', existing.get('email') if existing else None)
    email = normalize_string(email_source, 255)
    if email and not EMAIL_REGEX.match(email):
        errors.append("Email address is not valid.")
    payload['email'] = email

    phone_source = raw_data.get('phone', existing.get('phone') if existing else None)
    payload['phone'] = normalize_string(phone_source, 50)

    if account_id:
        payload['account_id'] = account_id
    else:
        errors.append("Account ID is required.")

    return payload, errors


def format_certificate_holder(row):
    """Format database row for API responses."""
    if not row:
        return None
    if not isinstance(row, dict):
        row = dict(row)

    holder = {
        'id': str(row.get('id')),
        'account_id': row.get('account_id'),
        'name': row.get('name'),
        'master_remarks': row.get('master_remarks'),
        'address_line1': row.get('address_line1'),
        'city': row.get('city'),
        'state': row.get('state'),
        'state_name': US_STATE_CHOICES.get((row.get('state') or '').upper()),
        'email': row.get('email'),
        'phone': row.get('phone'),
        'created_at': serialize_timestamp(row.get('created_at')),
        'updated_at': serialize_timestamp(row.get('updated_at'))
    }
    return holder


def database_not_configured_response():
    """Standard response when database features are unavailable."""
    return jsonify({
        'success': False,
        'error': 'Database connectivity is not configured for this environment.'
    }), 503

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


@app.route("/api/account/<account_id>/certificate-holders", methods=['GET'])
def list_certificate_holders(account_id):
    """List certificate holders for the given account."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'errors': [str(exc)]}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, account_id, name, master_remarks, address_line1, city, state, email, phone,
                   created_at, updated_at
            FROM certificate_holders
            WHERE account_id = %s
            ORDER BY name ASC, created_at DESC
        ''', (normalized_account_id,))
        rows = cur.fetchall()
        holders = [format_certificate_holder(row) for row in rows]

        return jsonify({
            'success': True,
            'account_id': normalized_account_id,
            'certificate_holders': holders,
            'state_options': US_STATE_OPTIONS
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/account/<account_id>/certificate-holders", methods=['POST'])
def create_certificate_holder(account_id):
    """Create a certificate holder for the account."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'errors': [str(exc)]}), 400

    try:
        raw_payload = request.get_json(force=True) or {}
    except Exception:
        raw_payload = {}

    sanitized, errors = sanitize_certificate_holder_payload(raw_payload, account_id=normalized_account_id)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO certificate_holders (
                account_id, name, master_remarks, address_line1, city, state, email, phone
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        ''', (
            normalized_account_id,
            sanitized.get('name'),
            sanitized.get('master_remarks'),
            sanitized.get('address_line1'),
            sanitized.get('city'),
            sanitized.get('state'),
            sanitized.get('email'),
            sanitized.get('phone')
        ))
        record = cur.fetchone()
        conn.commit()
        holder = format_certificate_holder(record)

        return jsonify({
            'success': True,
            'certificate_holder': holder
        }), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def fetch_certificate_holder(account_id, holder_id):
    """Fetch a certificate holder row."""
    normalized_account_id = normalize_account_id(account_id)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('''
            SELECT id, account_id, name, master_remarks, address_line1,
                   city, state, email, phone, created_at, updated_at
            FROM certificate_holders
            WHERE account_id = %s AND id = %s
        ''', (normalized_account_id, holder_id))
        row = cur.fetchone()
        return row
    finally:
        cur.close()
        conn.close()


@app.route("/api/account/<account_id>/certificate-holders/<holder_id>", methods=['GET'])
def get_certificate_holder(account_id, holder_id):
    """Retrieve a single certificate holder."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'errors': [str(exc)]}), 400

    try:
        row = fetch_certificate_holder(normalized_account_id, holder_id)
    except ValueError as exc:
        return jsonify({'success': False, 'errors': [str(exc)]}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    if not row:
        return jsonify({'success': False, 'error': 'Certificate holder not found'}), 404

    return jsonify({
        'success': True,
        'certificate_holder': format_certificate_holder(row),
        'state_options': US_STATE_OPTIONS
    })


@app.route("/api/account/<account_id>/certificate-holders/<holder_id>", methods=['PUT', 'PATCH'])
def update_certificate_holder(account_id, holder_id):
    """Update an existing certificate holder."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'errors': [str(exc)]}), 400

    existing = None
    try:
        existing = fetch_certificate_holder(normalized_account_id, holder_id)
    except ValueError as exc:
        return jsonify({'success': False, 'errors': [str(exc)]}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    if not existing:
        return jsonify({'success': False, 'error': 'Certificate holder not found'}), 404

    try:
        raw_payload = request.get_json(force=True) or {}
    except Exception:
        raw_payload = {}

    sanitized, errors = sanitize_certificate_holder_payload(raw_payload, existing=existing, account_id=normalized_account_id)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            UPDATE certificate_holders
            SET name = %s,
                master_remarks = %s,
                address_line1 = %s,
                city = %s,
                state = %s,
                email = %s,
                phone = %s,
                updated_at = NOW()
            WHERE account_id = %s AND id = %s
            RETURNING *
        ''', (
            sanitized.get('name'),
            sanitized.get('master_remarks'),
            sanitized.get('address_line1'),
            sanitized.get('city'),
            sanitized.get('state'),
            sanitized.get('email'),
            sanitized.get('phone'),
            normalized_account_id,
            holder_id
        ))
        record = cur.fetchone()
        if not record:
            conn.rollback()
            return jsonify({'success': False, 'error': 'Certificate holder not found'}), 404
        conn.commit()

        return jsonify({
            'success': True,
            'certificate_holder': format_certificate_holder(record)
        })
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/account/<account_id>/certificate-holders/<holder_id>", methods=['DELETE'])
def delete_certificate_holder(account_id, holder_id):
    """Delete a certificate holder."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'errors': [str(exc)]}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            DELETE FROM certificate_holders
            WHERE account_id = %s AND id = %s
            RETURNING id
        ''', (normalized_account_id, holder_id))
        result = cur.fetchone()
        if not result:
            conn.rollback()
            return jsonify({'success': False, 'error': 'Certificate holder not found'}), 404
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

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



def resolve_checkbox_state(saved_value):
    '''Return (pdf_state, field_state) tuples for checkbox-like fields.'''
    true_values = {"true", "1", "yes", "on", "checked", "x"}
    false_values = {"false", "0", "no", "off", "unchecked"}

    if isinstance(saved_value, bool):
        return ('/Yes' if saved_value else '/Off', 'Yes' if saved_value else 'Off')

    if saved_value is None:
        return '/Off', 'Off'

    value_str = str(saved_value).strip()
    if not value_str:
        return '/Off', 'Off'

    if value_str.startswith('/'):
        core = value_str[1:] or 'Off'
        return f'/{core}', core

    lowered = value_str.lower()
    if lowered in true_values:
        return '/Yes', 'Yes'
    if lowered in false_values:
        return '/Off', 'Off'

    return f'/{value_str}', value_str








def fill_checkboxes_with_pypdf(pdf_bytes, checkbox_values):
    '''Update checkbox states using pypdf to preserve original appearance streams.'''
    if not checkbox_values:
        return pdf_bytes, [], []

    if not PYPDF_AVAILABLE:
        missing = list(checkbox_values.keys())
        print(f"pypdf unavailable; cannot update {len(missing)} checkbox fields.")
        return pdf_bytes, [], missing

    reader = PdfReader(io.BytesIO(pdf_bytes))
    successful = set()

    def normalize_state_name(state):
        if not state:
            return '/Off'
        if isinstance(state, str):
            return state if state.startswith('/') else '/' + state
        return '/' + str(state)

    off_aliases = {'off', '0', 'false', 'unchecked'}
    on_aliases = {'yes', 'true', '1', 'on', 'checked', 'x'}

    def collect_available_states(annot):
        states = []
        ap = annot.get('/AP')
        if ap and hasattr(ap, 'get_object'):
            try:
                ap = ap.get_object()
            except Exception:
                ap = None
        if ap and isinstance(ap, dict):
            normal_ap = ap.get(NameObject('/N'), ap)
            if normal_ap and hasattr(normal_ap, 'get_object'):
                try:
                    normal_ap = normal_ap.get_object()
                except Exception:
                    normal_ap = None
            if normal_ap and isinstance(normal_ap, dict):
                for key in normal_ap.keys():
                    key_str = normalize_state_name(str(key))
                    if key_str not in states:
                        states.append(key_str)
        return states

    def choose_available_state(field_name, annot, desired_state):
        desired_state = normalize_state_name(desired_state)
        desired_lower = desired_state.lower()
        desired_bare = desired_lower.lstrip('/')

        available_states = collect_available_states(annot)
        if not available_states:
            print(f"Checkbox {field_name}: desired={desired_state}, available=NONE -> using desired")
            return desired_state

        lower_map = {state.lower(): state for state in available_states}
        bare_map = {state.lower().lstrip('/'): state for state in available_states}

        if desired_lower in lower_map:
            return lower_map[desired_lower]
        if desired_bare in bare_map:
            return bare_map[desired_bare]

        chosen = None
        if desired_bare in off_aliases:
            for alias in off_aliases:
                if alias in bare_map:
                    chosen = bare_map[alias]
                    break
        elif desired_bare in on_aliases:
            for alias in on_aliases:
                if alias in bare_map:
                    chosen = bare_map[alias]
                    break

        if chosen is None and desired_bare not in on_aliases:
            # When we expect an unchecked value but couldn't match, prefer any "off"-like state.
            for alias in off_aliases:
                if alias in bare_map:
                    chosen = bare_map[alias]
                    break

        if chosen is None and (desired_lower == '/off' or desired_bare in off_aliases):
            chosen = '/Off'

        if chosen is None:
            chosen = available_states[0]

        print(
            f"Checkbox {field_name}: desired={desired_state}, available={available_states}, chosen={chosen}"
        )
        return chosen

    for page_index, page in enumerate(reader.pages):
        annots = page.get('/Annots')
        if not annots:
            continue

        if hasattr(annots, 'get_object'):
            try:
                annots = annots.get_object()
            except Exception as annots_error:
                print(f"Page {page_index}: unable to resolve annotations ({annots_error})")
                continue

        if not isinstance(annots, (list, tuple)):
            annots = [annots]

        for annot_ref in annots:
            try:
                annot = annot_ref.get_object() if hasattr(annot_ref, 'get_object') else annot_ref
            except Exception as annot_error:
                print(f"Checkbox update skipped: unable to resolve annotation ({annot_error})")
                continue

            if annot is None:
                continue

            parent = annot.get('/Parent')
            if parent is not None and hasattr(parent, 'get_object'):
                try:
                    parent = parent.get_object()
                except Exception:
                    parent = None
            field_dict = parent or annot

            field_name_obj = field_dict.get('/T')
            if not field_name_obj:
                continue

            field_name = str(field_name_obj)
            if field_name not in checkbox_values:
                continue

            desired_pdf_state, _ = resolve_checkbox_state(checkbox_values[field_name])
            target_state = choose_available_state(field_name, annot, desired_pdf_state)
            state_name = NameObject(normalize_state_name(target_state))

            if normalize_state_name(target_state) != normalize_state_name(desired_pdf_state):
                print(
                    f"Checkbox {field_name}: using fallback state '{target_state}' for saved value '{desired_pdf_state}'"
                )

            try:
                annot.update({NameObject('/AS'): state_name})
                field_dict.update({NameObject('/V'): state_name})
                successful.add(field_name)
            except Exception as update_error:
                print(f"Checkbox '{field_name}' pypdf update failed: {update_error}")
                continue

    writer = PdfWriter()
    writer.clone_reader_document_root(reader)

    acro_form = writer._root_object.get(NameObject('/AcroForm'))
    if acro_form is not None and NameObject('/NeedAppearances') not in acro_form:
        acro_form[NameObject('/NeedAppearances')] = BooleanObject(False)

    output = io.BytesIO()
    writer.write(output)

    missing = [name for name in checkbox_values.keys() if name not in successful]
    return output.getvalue(), list(successful), missing





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
        print(f"Pre-filling PDF with {len(field_values)} saved field values")

        try:
            if PYMUPDF_AVAILABLE and field_values:
                # Load PDF with PyMuPDF
                pdf_doc = fitz.open(stream=pdf_content, filetype="pdf")

                filled_count = 0
                failed_fields = []
                checkbox_updates = {}

                # Simple approach: iterate through all pages and widgets
                for page_num in range(len(pdf_doc)):
                    page = pdf_doc[page_num]

                    # Get all widgets on this page
                    widgets = list(page.widgets())

                    for widget in widgets:
                        field_name = widget.field_name

                        # Check if we have a saved value for this field
                        if field_name in field_values:
                            saved_value = field_values[field_name]

                            # Skip empty values for text fields only
                            # For checkboxes, we need to process /Off values too
                            field_type = widget.field_type_string
                            field_type_lower = (field_type or '').lower()
                            is_checkbox_like = field_type_lower in {'checkbox', 'button', 'btn', 'radiobutton'}

                            if not is_checkbox_like and (not saved_value or saved_value == ''):
                                continue

                            try:
                                if field_type_lower == 'text':
                                    text_value = str(saved_value)
                                    if text_value.startswith('/') and len(text_value) > 1:
                                        core = text_value[1:].lower()
                                        if core in {'yes', 'on', '1', 'true', 'y'}:
                                            text_value = 'Yes'
                                        elif core in {'no', 'off', '0', 'false', 'n'}:
                                            text_value = 'No'
                                    widget.field_value = text_value
                                    widget.update()
                                    filled_count += 1

                                elif field_type_lower in {'checkbox', 'button', 'btn'}:
                                    if PYPDF_AVAILABLE:
                                        checkbox_updates[field_name] = saved_value
                                        continue

                                    pdf_state, field_state = resolve_checkbox_state(saved_value)
                                    try:
                                        widget.field_value = field_state
                                        widget.update()
                                        filled_count += 1
                                    except Exception as widget_error:
                                        failed_fields.append((field_name, str(widget_error)))
                                        print(f"Checkbox '{field_name}' fallback update failed: {widget_error}")
                                    continue
                                elif field_type_lower == 'radiobutton':
                                    if saved_value in [True, 'true', 'True', '1', 'Yes', 'yes', 'On', 'X']:
                                        widget.field_value = 'X'
                                    else:
                                        widget.field_value = 'Off'
                                    widget.update()
                                    filled_count += 1
                                    print(f"[radio] Set radio button '{field_name}' to: {widget.field_value}")

                                else:
                                    widget.field_value = str(saved_value)
                                    widget.update()
                                    filled_count += 1
                                    print(f"[generic] Filled field '{field_name}': '{saved_value}'")

                            except Exception as field_error:
                                failed_fields.append((field_name, str(field_error)))
                                print(f"? Failed to fill '{field_name}': {field_error}")

                # Generate PDF bytes from PyMuPDF result
                filled_pdf_content = pdf_doc.write()
                pdf_doc.close()

                checkbox_successes = []
                checkbox_failures = []
                if checkbox_updates and PYPDF_AVAILABLE:
                    filled_pdf_content, checkbox_successes, checkbox_failures = fill_checkboxes_with_pypdf(
                        filled_pdf_content,
                        checkbox_updates,
                    )
                    filled_count += len(checkbox_successes)
                    summary_msg = f"Checkbox states applied via pypdf: {checkbox_successes[:5]} (total {len(checkbox_successes)} successes, {len(checkbox_failures)} failures)"
                    print(summary_msg)
                    if checkbox_failures:
                        for failed_name in checkbox_failures:
                            failed_fields.append((failed_name, 'checkbox update failed'))
                        print(f"Checkbox updates failed for: {checkbox_failures}")
                elif checkbox_updates:
                    print(f"PyPDF unavailable; {len(checkbox_updates)} checkboxes filled via PyMuPDF fallback appearance.")

                print(f"=== PRE-FILL COMPLETE ===")
                print(f"Successfully filled: {filled_count} fields")
                print(f"Failed fields: {len(failed_fields)}")
                if failed_fields:
                    print(f"Failures: {failed_fields[:5]}")  # Show first 5

                from flask import Response
                return Response(
                    filled_pdf_content,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': f'inline; filename="{template_name}_filled.pdf"',
                        'Access-Control-Allow-Origin': '*',
                        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
                        'Pragma': 'no-cache',
                        'Expires': '0'
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
            import traceback
            traceback.print_exc()
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


@app.route('/api/debug/pymupdf-test/<template_id>/<account_id>')
def debug_pymupdf_test(template_id, account_id):
    '''Run a small PyMuPDF fill test and return diagnostic information.'''
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
        field_values_raw = result.get('field_values') or {}

        if isinstance(field_values_raw, str):
            try:
                field_values = json.loads(field_values_raw)
            except json.JSONDecodeError:
                field_values = {}
        else:
            field_values = field_values_raw or {}

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
            return jsonify({'error': 'No PDF content available'}), 404

        debug_info = {
            'template_id': template_id,
            'account_id': account_id,
            'template_name': template_name,
            'field_values_count': len(field_values),
            'non_empty_count': len({k: v for k, v in field_values.items() if v and str(v).strip()}),
            'pymupdf_available': PYMUPDF_AVAILABLE,
            'pdf_size': len(pdf_content),
            'test_results': {}
        }

        if PYMUPDF_AVAILABLE:
            try:
                pdf_doc = fitz.open(stream=pdf_content, filetype='pdf')

                form_fields = list(pdf_doc[0].widgets()) if pdf_doc.page_count else []
                debug_info['test_results']['form_fields_found'] = len(form_fields)
                debug_info['test_results']['form_field_names'] = [widget.field_name for widget in form_fields[:10]]

                filled_count = 0
                failed_fields = []
                checkbox_updates = {}

                test_fields = [(name, value) for name, value in field_values.items()
                               if value and str(value).strip()][:5]

                for field_name, saved_value in test_fields:
                    field_found = False
                    for widget in form_fields:
                        if widget.field_name == field_name:
                            field_found = True
                            field_type = widget.field_type_string
                            field_type_lower = (field_type or '').lower()

                            try:
                                if field_type_lower == 'text':
                                    text_value = str(saved_value)
                                    if text_value.startswith('/') and len(text_value) > 1:
                                        core = text_value[1:].lower()
                                        if core in {'yes', 'on', '1', 'true', 'y'}:
                                            text_value = 'Yes'
                                        elif core in {'no', 'off', '0', 'false', 'n'}:
                                            text_value = 'No'
                                    widget.field_value = text_value
                                    widget.update()
                                    filled_count += 1
                                elif field_type_lower in {'checkbox', 'button', 'btn'}:
                                    if PYPDF_AVAILABLE:
                                        checkbox_updates[field_name] = saved_value
                                        continue

                                    pdf_state, field_state = resolve_checkbox_state(saved_value)
                                    try:
                                        widget.field_value = field_state
                                        widget.update()
                                        filled_count += 1
                                        debug_info['test_results'][f'field_{field_name}'] = {
                                            'type': field_type,
                                            'value': saved_value,
                                            'status': 'filled'
                                        }
                                    except Exception as widget_error:
                                        debug_info['test_results'][f'field_{field_name}'] = {
                                            'type': field_type,
                                            'value': saved_value,
                                            'status': 'error',
                                            'error': str(widget_error)
                                        }
                                        failed_fields.append(field_name)
                                    continue
                                elif field_type_lower == 'radiobutton':
                                    widget.field_value = str(saved_value)
                                    widget.update()
                                    filled_count += 1
                                else:
                                    widget.field_value = str(saved_value)
                                    widget.update()
                                    filled_count += 1

                                debug_info['test_results'][f'field_{field_name}'] = {
                                    'type': field_type,
                                    'value': saved_value,
                                    'status': 'filled'
                                }
                            except Exception as widget_error:
                                debug_info['test_results'][f'field_{field_name}'] = {
                                    'type': field_type,
                                    'value': saved_value,
                                    'status': 'error',
                                    'error': str(widget_error)
                                }
                                failed_fields.append(field_name)
                            break

                    if not field_found:
                        debug_info['test_results'][f'field_{field_name}'] = {
                            'value': saved_value,
                            'status': 'not_found'
                        }
                        failed_fields.append(field_name)

                filled_pdf_content = pdf_doc.write()
                pdf_doc.close()

                checkbox_successes = []
                checkbox_failures = []
                if checkbox_updates and PYPDF_AVAILABLE:
                    filled_pdf_content, checkbox_successes, checkbox_failures = fill_checkboxes_with_pypdf(
                        filled_pdf_content,
                        checkbox_updates,
                    )
                    filled_count += len(checkbox_successes)
                    for name in checkbox_successes:
                        debug_info['test_results'][f'field_{name}'] = {
                            'type': 'checkbox',
                            'value': checkbox_updates[name],
                            'status': 'filled (pypdf)'
                        }
                    for name in checkbox_failures:
                        debug_info['test_results'][f'field_{name}'] = {
                            'type': 'checkbox',
                            'value': checkbox_updates.get(name),
                            'status': 'error',
                            'error': 'checkbox update failed'
                        }
                        failed_fields.append(name)
                    debug_info['test_results']['checkbox_summary'] = {
                        'attempted': len(checkbox_updates),
                        'successes': len(checkbox_successes),
                        'failures': len(checkbox_failures)
                    }
                elif checkbox_updates:
                    debug_info['test_results']['checkbox_notice'] = 'PyPDF unavailable; checkboxes filled via PyMuPDF fallback.'

                debug_info['test_results']['checkbox_successes'] = checkbox_successes
                debug_info['test_results']['checkbox_failures'] = checkbox_failures
                debug_info['test_results']['filled_count'] = filled_count
                debug_info['test_results']['failed_fields'] = failed_fields
                debug_info['test_results']['filled_pdf_size'] = len(filled_pdf_content)
                debug_info['test_results']['success'] = True
            except Exception as pymupdf_error:
                debug_info['test_results']['error'] = str(pymupdf_error)
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
                                # For checkboxes, prioritize /AS (appearance state) over /V (value)
                                # because /AS contains /Off, /Yes, /1, etc.
                                if hasattr(field_obj, 'get') and field_obj.get('/AS'):
                                    field_value = str(field_obj.get('/AS'))
                                elif hasattr(field_obj, 'get') and field_obj.get('/V'):
                                    field_value = str(field_obj.get('/V'))
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
                                                # For checkboxes, prioritize /AS (appearance state) over /V (value)
                                                if '/AS' in field_obj:  # Appearance state (for checkboxes)
                                                    field_value = str(field_obj['/AS'])
                                                elif '/V' in field_obj:  # Field value
                                                    field_value = str(field_obj['/V'])
                                                extracted_fields[field_name] = field_value
                                                print(f"Field {i+1}: {field_name} = '{field_value}'")
                                        except Exception as field_error:
                                            print(f"Error processing field {i}: {field_error}")
                            else:
                                print("No /AcroForm found in PDF root")
                        except Exception as e:
                            print(f"Manual AcroForm extraction failed: {e}")
                    
                    print(f"Final extracted {len(extracted_fields)} fields from PDF content")
                    
                    # Normalize checkbox values: empty strings should be /Off for checkbox fields
                    def is_checkbox_field_name(field_name):
                        """Check if a field is likely a checkbox based on name patterns"""
                        checkbox_indicators = ['indicator', 'checkbox', 'check', 'box']
                        return any(indicator in field_name.lower() for indicator in checkbox_indicators)
                    
                    for field_name, field_value in list(extracted_fields.items()):
                        if is_checkbox_field_name(field_name):
                            # If checkbox field has empty or whitespace-only value, set to /Off
                            if not field_value or not str(field_value).strip():
                                extracted_fields[field_name] = '/Off'
                                print(f"Normalized empty checkbox '{field_name}' to '/Off'")
                    
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
            SELECT id, field_values FROM template_data 
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, template_id))

        existing_data = cur.fetchone()

        # Get existing field values for merging
        existing_field_values = {}
        if existing_data and existing_data.get('field_values'):
            try:
                field_values_raw = existing_data['field_values']
                print(f"Existing data type: {type(field_values_raw)}")
                print(f"Existing data preview: {str(field_values_raw)[:500]}")
                
                # Handle different data types
                if isinstance(field_values_raw, dict):
                    existing_field_values = field_values_raw
                elif isinstance(field_values_raw, str):
                    existing_field_values = json.loads(field_values_raw)
                else:
                    print(f"Unexpected field_values type: {type(field_values_raw)}")
                    existing_field_values = {}
                
                print(f"Found existing field values: {len(existing_field_values)} fields")
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Failed to parse existing field values: {e}")
                print(f"Raw data sample: {str(existing_data.get('field_values', ''))[:200]}")
                existing_field_values = {}

        # Merge logic: For checkboxes, preserve checked state
        def is_checkbox_field(field_name):
            """Check if a field is likely a checkbox based on name patterns"""
            checkbox_indicators = ['indicator', 'checkbox', 'check', 'box']
            force_text_fields = {
                'WorkersCompensationEmployersLiability_AnyPersonsExcludedIndicator_A',
            }

            if field_name in force_text_fields:
                return False

            is_checkbox = any(indicator in field_name.lower() for indicator in checkbox_indicators)
            if is_checkbox:
                print(f"Field '{field_name}' identified as checkbox")
            return is_checkbox
        
        def is_checkbox_checked(value):
            """Determine if a checkbox value represents 'checked'"""
            checked_values = ['/1', '/Yes', '/On', 'Yes', '1', 'On', 'true', 'True', True, 'Y', 'y']
            return str(value).strip() in checked_values if value else False
        
        def normalize_checkbox_value(value):
            """Convert various checkbox formats to standard '/Yes' or '/Off'"""
            if is_checkbox_checked(value):
                return '/Yes'
            return '/Off'

        print(f"\n=== MERGE LOGIC DEBUG ===")
        print(f"Current fields: {len(final_field_values)}")
        print(f"Existing fields: {len(existing_field_values)}")
        
        # Show sample of existing values
        if existing_field_values:
            sample_existing = list(existing_field_values.items())[:3]
            print(f"Sample existing values: {sample_existing}")
        
        merged_field_values = {}
        checkbox_count = 0
        preserved_count = 0
        
        for field_name, current_value in final_field_values.items():
            if is_checkbox_field(field_name):
                checkbox_count += 1
                # Checkbox merge logic
                existing_value = existing_field_values.get(field_name, '')
                
                print(f"\n--- CHECKBOX MERGE: {field_name} ---")
                print(f"  Current value: '{current_value}' (type: {type(current_value)})")
                print(f"  Existing value: '{existing_value}' (type: {type(existing_value)})")
                
                current_checked = is_checkbox_checked(current_value)
                existing_checked = is_checkbox_checked(existing_value)
                
                print(f"  Current checked: {current_checked}, Existing checked: {existing_checked}")
                
                # Check if current value is explicitly set (either /Yes or /Off)
                current_is_explicit = str(current_value).strip() in ['/Yes', '/Off', '/On', '/1', 'Yes', 'No', 'On', 'Off', '1', '0', 'true', 'false', 'True', 'False', 'Y', 'N', 'y', 'n']
                
                if current_is_explicit:
                    # Current value is explicitly set (user made a choice) - always use it
                    merged_field_values[field_name] = normalize_checkbox_value(current_value)
                    if current_checked:
                        print(f"  → Explicitly checked, saving as /Yes")
                    else:
                        print(f"  → Explicitly unchecked, saving as /Off")
                elif existing_checked:
                    # Current value is empty/missing, preserve previously checked state
                    merged_field_values[field_name] = normalize_checkbox_value(existing_value)
                    preserved_count += 1
                    print(f"  → Current empty, preserving previously checked state (/Yes)")
                else:
                    # Both empty/unchecked - save as unchecked
                    merged_field_values[field_name] = '/Off'
                    print(f"  → Both empty/unchecked, saving as /Off")
            else:
                # For text fields, always use current value
                merged_field_values[field_name] = current_value
        
        print(f"\n=== MERGE SUMMARY ===")
        print(f"Total checkboxes processed: {checkbox_count}")
        print(f"Checkboxes preserved: {preserved_count}")
        print(f"Final merged fields: {len(merged_field_values)}")
        print(f"=== END MERGE DEBUG ===\n")

        print("Saving field values for template {0}, account {1}: {2} fields (merged from {3} current + {4} existing)".format(
            template_id, account_id, len(merged_field_values), len(final_field_values), len(existing_field_values)))
        
        if merged_field_values:
            print("Merged field sample:", list(merged_field_values.items())[:5])
            non_empty_saved = {k: v for k, v in merged_field_values.items() if v and str(v).strip()}
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
            ''', (json.dumps(merged_field_values), account_id, template_id))
            print(f"UPDATE query executed, affected rows: {cur.rowcount}")
        else:
            print(f"Inserting new template_data record for account {account_id}, template {template_id}")
            cur.execute('''
                INSERT INTO template_data (account_id, template_id, field_values)
                VALUES (%s, %s, %s)
            ''', (account_id, template_id, json.dumps(merged_field_values)))
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
            'field_count': len(merged_field_values),
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
