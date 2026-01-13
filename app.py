from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
from functools import wraps
import os
import io
import uuid
import json
from pathlib import Path
from datetime import datetime
import base64
import re
import zipfile
import traceback
import requests

# Salesforce session validation cache (sid -> {valid: bool, expires: timestamp})
sf_session_cache = {}
SF_SESSION_CACHE_TTL = 300  # 5 minutes

def extract_sf_instance_url(instance_url):
    """Extract base instance URL from Salesforce Partner Server URL or full URL"""
    if not instance_url:
        return None
    # Handle Partner_Server_URL which looks like: https://na1.salesforce.com/services/Soap/u/26.0/00D...
    # We just need the base: https://na1.salesforce.com
    try:
        from urllib.parse import urlparse
        parsed = urlparse(instance_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except:
        pass
    return instance_url

def validate_salesforce_session(sid, instance_url=None):
    """Validate a Salesforce session ID by calling SF API"""
    if not sid:
        return False, "No session ID provided"

    # Check cache first
    cached = sf_session_cache.get(sid)
    if cached and cached['expires'] > datetime.utcnow().timestamp():
        return cached['valid'], cached.get('error', '')

    # Extract base URL from instance_url (handles Partner_Server_URL format)
    base_url = extract_sf_instance_url(instance_url)
    if not base_url:
        base_url = os.environ.get('SF_INSTANCE_URL', 'https://login.salesforce.com')

    # Call Salesforce to validate the session
    try:
        # Use the UserInfo endpoint to validate session
        response = requests.get(
            f"{base_url}/services/oauth2/userinfo",
            headers={'Authorization': f'Bearer {sid}'},
            timeout=10
        )

        if response.status_code == 200:
            # Valid session - cache it
            sf_session_cache[sid] = {
                'valid': True,
                'expires': datetime.utcnow().timestamp() + SF_SESSION_CACHE_TTL,
                'user_info': response.json()
            }
            return True, None
        else:
            # Invalid session
            sf_session_cache[sid] = {
                'valid': False,
                'expires': datetime.utcnow().timestamp() + 60,  # Cache failures for 1 min
                'error': 'Invalid session'
            }
            return False, "Invalid or expired Salesforce session"
    except requests.exceptions.RequestException as e:
        return False, f"Failed to validate session: {str(e)}"

def require_sf_session(f):
    """Decorator to require valid Salesforce session for API endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get session from query params (support both naming conventions)
        sid = request.args.get('sfSession') or request.args.get('sid') or request.headers.get('X-SF-Session-Id')
        org_id = request.args.get('sfOrg') or request.args.get('instance_url') or request.headers.get('X-SF-Instance-Url')

        if not sid:
            return jsonify({'error': 'Authentication required', 'code': 'NO_SESSION'}), 401

        # For org ID, we need to construct the instance URL
        # If it's an org ID (starts with 00D), use login.salesforce.com
        # Otherwise treat it as instance URL
        instance_url = None
        if org_id and not org_id.startswith('http'):
            # It's an org ID, use default login URL
            instance_url = os.environ.get('SF_INSTANCE_URL', 'https://login.salesforce.com')
        else:
            instance_url = org_id

        valid, error = validate_salesforce_session(sid, instance_url)
        if not valid:
            return jsonify({'error': error or 'Invalid session', 'code': 'INVALID_SESSION'}), 401

        return f(*args, **kwargs)
    return decorated_function

# Optional imports with fallbacks

LOCAL_TEMPLATE_DIR = Path(__file__).resolve().parent / "database" / "templates"
MASTER_TEMPLATE_CONFIG = {
    "acord24": {
        "filename": "acord24.pdf",
        "display_name": "ACORD 24 - Certificate of Property Insurance",
    },
    "acord25": {
        "filename": "acord25.pdf",
        "display_name": "ACORD 25 - Certificate of Liability Insurance",
    },
    "acord27": {
        "filename": "acord27.pdf",
        "display_name": "ACORD 27 - Evidence of Property Insurance",
    },
    "acord28": {
        "filename": "acord28.pdf",
        "display_name": "ACORD 28 - Evidence of Commercial Property Insurance",
    },
    "acord30": {
        "filename": "acord30.pdf",
        "display_name": "ACORD 30 - Evidence of Commercial Crime Insurance",
    },
    "acord35": {
        "filename": "acord35.pdf",
        "display_name": "ACORD 35 - Evidence of Commercial Inland Marine Insurance",
    },
    "acord36": {
        "filename": "acord36.pdf",
        "display_name": "ACORD 36 - Agent of Record Change",
    },
    "acord37": {
        "filename": "acord37.pdf",
        "display_name": "ACORD 37 - Statement of No Loss",
    },
    "acord125": {
        "filename": "acord125.pdf",
        "display_name": "ACORD 125 - Commercial Insurance Application",
    },
    "acord126": {
        "filename": "acord126.pdf",
        "display_name": "ACORD 126 - Commercial General Liability Application",
    },
    "acord130": {
        "filename": "acord130.pdf",
        "display_name": "ACORD 130 - Evidence of Commercial Property Insurance",
    },
    "acord131": {
        "filename": "acord131.pdf",
        "display_name": "ACORD 131 - Umbrella Application",
    },
    "acord140": {
        "filename": "acord140.pdf",
        "display_name": "ACORD 140 - Evidence of Commercial Property Insurance",
    },
}
LOCAL_TEMPLATE_FILES = {key: value["filename"] for key, value in MASTER_TEMPLATE_CONFIG.items()}

# Standard Certificate Holder field mapping (used as default for most templates)
DEFAULT_CERTIFICATE_HOLDER_FIELDS = {
    "name": "CertificateHolder_FullName_A",
    "address_line1": "CertificateHolder_MailingAddress_LineOne_A",
    "address_line2": "CertificateHolder_MailingAddress_LineTwo_A",
    "city": "CertificateHolder_MailingAddress_CityName_A",
    "state": "CertificateHolder_MailingAddress_StateOrProvinceCode_A",
    "postal_code": "CertificateHolder_MailingAddress_PostalCode_A",
}

CERTIFICATE_HOLDER_FIELD_MAPPINGS = {
    # Standard templates using common field names
    "acord24": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
    "acord25": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
        "master_remarks": "CertificateOfLiabilityInsurance_ACORDForm_RemarkText_A",
    },
    "acord27": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
        "master_remarks": "EvidenceOfProperty_RemarkText_A",
    },
    "acord28": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
        "master_remarks": "CertificateOfLiabilityInsurance_ACORDForm_RemarkText_A",
    },
    "acord30": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
        "master_remarks": "CertificateOfLiabilityInsurance_ACORDForm_RemarkText_A",
    },
    "acord35": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
    "acord36": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
    "acord37": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
    "acord125": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
    "acord126": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
    "acord130": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
    "acord131": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
    "acord140": {
        **DEFAULT_CERTIFICATE_HOLDER_FIELDS,
    },
}

# Named Insured (Applicant) field mappings - for injecting applicant data from Supabase
DEFAULT_NAMED_INSURED_FIELDS = {
    "name": "NamedInsured_FullName_A",
    "address_line1": "NamedInsured_MailingAddress_LineOne_A",
    "address_line2": "NamedInsured_MailingAddress_LineTwo_A",
    "city": "NamedInsured_MailingAddress_CityName_A",
    "state": "NamedInsured_MailingAddress_StateOrProvinceCode_A",
    "postal_code": "NamedInsured_MailingAddress_PostalCode_A",
    "email": "NamedInsured_Primary_EmailAddress_A",
    "phone": "NamedInsured_Primary_PhoneNumber_A",
}

NAMED_INSURED_FIELD_MAPPINGS = {
    "acord24": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord25": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord27": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord28": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord30": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord35": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord36": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord37": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord125": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord126": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord130": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord131": {**DEFAULT_NAMED_INSURED_FIELDS},
    "acord140": {**DEFAULT_NAMED_INSURED_FIELDS},
}

FIELD_MAPPING_SCOPES = {'certificate_holder', 'agency', 'named_insured'}

# Agency/Producer field mapping
# Maps database column names to PDF field names
# Agency fields (company info):
#   - name, street, suite, city, state, zip = Agency address block
# Producer fields (contact person):
#   - producerName, producerPhone, producerEmail = Contact person details
DEFAULT_AGENCY_FIELD_MAPPING = {
    # Agency/Company info
    "name": "Agency_FullName_A",
    "street": "Producer_MailingAddress_LineOne_A",
    "suite": "Producer_MailingAddress_LineTwo_A",
    "city": "Producer_MailingAddress_CityName_A",
    "state": "Producer_MailingAddress_StateOrProvinceCode_A",
    "zip": "Producer_MailingAddress_PostalCode_A",
    "fax": "Producer.Fax",
    # Producer/Contact person info
    "producerName": "Producer_ContactPerson_FullName_A",
    "producerPhone": "Producer_ContactPerson_PhoneNumber_A",
    "producerEmail": "Producer_ContactPerson_EmailAddress_A",
}

def get_certificate_holder_field_map(template_type):
    """Return the field-name mapping for a given template type."""
    mapping = resolve_field_mapping(template_type, 'certificate_holder')
    if mapping:
        return mapping
    default_map = CERTIFICATE_HOLDER_FIELD_MAPPINGS.get("acord25", {})
    return default_map


def normalize_template_key(template_key):
    if not template_key:
        return 'default'
    return str(template_key).strip().lower() or 'default'


def get_default_field_mapping(template_key, scope):
    normalized_key = normalize_template_key(template_key)
    if scope == 'certificate_holder':
        default_map = CERTIFICATE_HOLDER_FIELD_MAPPINGS.get(normalized_key)
        if default_map:
            return dict(default_map)
        fallback = CERTIFICATE_HOLDER_FIELD_MAPPINGS.get('acord25', {})
        return dict(fallback)
    if scope == 'agency':
        return dict(DEFAULT_AGENCY_FIELD_MAPPING)
    if scope == 'named_insured':
        default_map = NAMED_INSURED_FIELD_MAPPINGS.get(normalized_key)
        if default_map:
            return dict(default_map)
        return dict(DEFAULT_NAMED_INSURED_FIELDS)
    return {}


def get_named_insured_field_map(template_type):
    """Return the field-name mapping for Named Insured fields for a given template type."""
    mapping = resolve_field_mapping(template_type, 'named_insured')
    if mapping:
        return mapping
    default_map = NAMED_INSURED_FIELD_MAPPINGS.get(normalize_template_key(template_type), {})
    if default_map:
        return default_map
    return dict(DEFAULT_NAMED_INSURED_FIELDS)


def fetch_field_mapping_from_db(template_key, scope, cur=None):
    if not PSYCOPG2_AVAILABLE:
        return None
    normalized_key = normalize_template_key(template_key)
    own_connection = False
    conn = None
    cursor = cur
    try:
        if cursor is None:
            conn = get_db()
            cursor = conn.cursor()
            own_connection = True
        cursor.execute(
            '''
            SELECT fields
            FROM field_mappings
            WHERE template_key = %s AND mapping_scope = %s
            ''',
            (normalized_key, scope)
        )
        row = cursor.fetchone()
        if row and row.get('fields'):
            return dict(row['fields'])
        if normalized_key != 'default':
            cursor.execute(
                '''
                SELECT fields
                FROM field_mappings
                WHERE template_key = %s AND mapping_scope = %s
                ''',
                ('default', scope)
            )
            fallback = cursor.fetchone()
            if fallback and fallback.get('fields'):
                return dict(fallback['fields'])
    except Exception as db_error:
        print(f"Field mapping lookup failed for template '{template_key}' ({scope}): {db_error}")
        return None
    finally:
        if own_connection:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    return None


def resolve_field_mapping(template_key, scope, cur=None, include_source=False):
    mapping = fetch_field_mapping_from_db(template_key, scope, cur=cur)
    source = 'database'
    if not mapping:
        mapping = get_default_field_mapping(template_key, scope)
        source = 'default'
    if include_source:
        return mapping, source
    return mapping


def save_field_mapping_to_db(template_key, scope, fields, updated_by=None):
    if not PSYCOPG2_AVAILABLE:
        raise RuntimeError("Database is not available for storing mappings.")
    normalized_key = normalize_template_key(template_key)
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            '''
            INSERT INTO field_mappings (template_key, mapping_scope, fields, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (template_key, mapping_scope)
            DO UPDATE SET
                fields = EXCLUDED.fields,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            ''',
            (normalized_key, scope, Json(fields), updated_by)
        )
        conn.commit()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

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

# Tracks whether the master_templates table includes the pdf_blob column.
PDF_BLOB_COLUMN_AVAILABLE = None

app = Flask(__name__, static_folder='frontend/build', static_url_path='')
CORS(app)

# Initialize Supabase (for storage only) - with better error handling
supabase = None
if SUPABASE_AVAILABLE:
    try:
        supabase_url = os.environ.get('SUPABASE_URL')
        supabase_key = os.environ.get('SUPABASE_KEY')

        # Debug: check what env vars we're getting
        print(f"=== SUPABASE INIT DEBUG ===")
        print(f"SUPABASE_URL present: {bool(supabase_url)}")
        print(f"SUPABASE_KEY present: {bool(supabase_key)}")
        if supabase_url:
            # Show just the domain part for debugging without exposing full URL
            url_parts = supabase_url.split('.')
            if len(url_parts) > 0:
                print(f"SUPABASE_URL domain starts with: {url_parts[0][-8:]}")

        if supabase_url and supabase_key:
            supabase = create_client(supabase_url, supabase_key)
            print("Supabase client initialized successfully")
        else:
            missing = []
            if not supabase_url:
                missing.append('SUPABASE_URL')
            if not supabase_key:
                missing.append('SUPABASE_KEY')
            print(f"Warning: Missing Supabase env vars: {', '.join(missing)}. Storage functionality will be limited.")
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


def ensure_pdf_blob_column(cur=None):
    """
    Detect whether the master_templates table has a pdf_blob column.
    Caches the result globally to avoid repeated introspection.
    """
    global PDF_BLOB_COLUMN_AVAILABLE
    if PDF_BLOB_COLUMN_AVAILABLE is not None:
        return PDF_BLOB_COLUMN_AVAILABLE

    if not PSYCOPG2_AVAILABLE:
        PDF_BLOB_COLUMN_AVAILABLE = False
        return PDF_BLOB_COLUMN_AVAILABLE

    close_conn = False
    conn = None
    cursor = cur
    try:
        if cursor is None:
            conn = get_db()
            cursor = conn.cursor()
            close_conn = True

        cursor.execute(
            '''
            SELECT 1
            FROM information_schema.columns
            WHERE LOWER(table_name) = 'master_templates'
              AND column_name = 'pdf_blob'
            LIMIT 1
            '''
        )
        PDF_BLOB_COLUMN_AVAILABLE = cursor.fetchone() is not None
        if not PDF_BLOB_COLUMN_AVAILABLE:
            print("master_templates.pdf_blob column missing; operating without DB-stored PDFs.")
    except Exception as detection_error:
        if cursor and cursor.connection:
            cursor.connection.rollback()
        print(f"Warning: Unable to determine master_templates.pdf_blob availability: {detection_error}")
        PDF_BLOB_COLUMN_AVAILABLE = False
    finally:
        if close_conn and cursor:
            cursor.close()
        if close_conn and conn:
            conn.close()

    return PDF_BLOB_COLUMN_AVAILABLE

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
        pdf_blob_supported = ensure_pdf_blob_column(cur)
        
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

        # Field mappings editable via admin UI
        cur.execute('''
            CREATE TABLE IF NOT EXISTS field_mappings (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                template_key VARCHAR(100) NOT NULL,
                mapping_scope VARCHAR(50) NOT NULL,
                fields JSONB NOT NULL DEFAULT '{}'::JSONB,
                updated_by VARCHAR(100),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(template_key, mapping_scope)
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

        # Agency Settings - for storing agency/producer data per account
        cur.execute('''
            CREATE TABLE IF NOT EXISTS agency_settings (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                account_id VARCHAR(18) NOT NULL,
                name VARCHAR(255),
                street VARCHAR(255),
                suite VARCHAR(100),
                city VARCHAR(120),
                state VARCHAR(2),
                zip VARCHAR(20),
                phone VARCHAR(50),
                fax VARCHAR(50),
                email VARCHAR(255),
                producer_name VARCHAR(255),
                producer_phone VARCHAR(50),
                producer_email VARCHAR(255),
                signature_image TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(account_id)
            );
        ''')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_agency_settings_account ON agency_settings(account_id);')

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


def is_checkbox_field_name(field_name):
    """Heuristic to detect checkbox/radio fields from their name."""
    if not field_name:
        return False
    field_lower = field_name.lower()
    if field_lower.endswith('text'):
        return False
    checkbox_indicators = ['indicator', 'checkbox', 'check', 'box']
    return any(token in field_lower for token in checkbox_indicators)


def normalize_checkbox_value(value):
    """Normalize checkbox values so PDF rendering receives /Yes or /Off."""
    if value is None:
        return '/Off'
    normalized = str(value).strip().lower()
    if normalized in {'/yes', 'yes', 'true', '1', 'on', 'y', 'checked', 'x'}:
        return '/Yes'
    if normalized in {'/off', 'no', 'false', '0', 'off', 'n', ''}:
        return '/Off'
    return '/Yes'

def is_checkbox_checked(value):
    """Determine if a checkbox value represents 'checked'."""
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized in {'/1', '/yes', 'yes', 'true', '1', 'on', 'y', 'checked', 'x'}


def serialize_timestamp(value):
    """Return ISO formatted timestamp when possible."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def ensure_certificate_holder_extended_columns():
    """Ensure optional address fields exist on certificate_holders table."""
    if not PSYCOPG2_AVAILABLE:
        return
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS address_line2 VARCHAR(255);')
        cur.execute('ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20);')
        conn.commit()
    except Exception as error:
        if conn:
            conn.rollback()
        print("Warning: unable to ensure extended certificate holder columns:", error)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def ensure_generated_certificates_table():
    """Ensure the generated_certificates table exists with required columns."""
    if not PSYCOPG2_AVAILABLE:
        return

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        # Create table if not exists
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS generated_certificates (
                id UUID PRIMARY KEY,
                account_id VARCHAR(18) NOT NULL,
                template_id UUID,
                certificate_holder_id UUID,
                filename TEXT,
                storage_path TEXT,
                pdf_blob BYTEA,
                generated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            )
            '''
        )

        # Add missing columns to existing table (migration)
        cur.execute('ALTER TABLE generated_certificates ADD COLUMN IF NOT EXISTS certificate_holder_id UUID;')
        cur.execute('ALTER TABLE generated_certificates ADD COLUMN IF NOT EXISTS filename TEXT;')
        cur.execute('ALTER TABLE generated_certificates ADD COLUMN IF NOT EXISTS pdf_blob BYTEA;')

        cur.execute(
            '''
            CREATE INDEX IF NOT EXISTS idx_generated_certificates_account
            ON generated_certificates(account_id)
            '''
        )
        cur.execute(
            '''
            CREATE INDEX IF NOT EXISTS idx_generated_certificates_holder
            ON generated_certificates(certificate_holder_id)
            '''
        )
        conn.commit()
        print("[ensure_generated_certificates_table] Table and columns ensured successfully")
    except Exception as error:
        if conn:
            conn.rollback()
        print(f"Warning: unable to ensure generated_certificates table: {error}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


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

    address_line2_source = raw_data.get('address_line2', existing.get('address_line2') if existing else None)
    payload['address_line2'] = normalize_string(address_line2_source, 255)

    city_source = raw_data.get('city', existing.get('city') if existing else None)
    payload['city'] = normalize_string(city_source, 120)

    postal_code_source = raw_data.get('postal_code', existing.get('postal_code') if existing else None)
    payload['postal_code'] = normalize_string(postal_code_source, 20)

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
        'address_line2': row.get('address_line2'),
        'city': row.get('city'),
        'state': row.get('state'),
        'postal_code': row.get('postal_code'),
        'state_name': US_STATE_CHOICES.get((row.get('state') or '').upper()),
        'email': row.get('email'),
        'phone': row.get('phone'),
        'created_at': serialize_timestamp(row.get('created_at')),
        'updated_at': serialize_timestamp(row.get('updated_at'))
    }
    return holder

def decode_data_url(data_url):
    """Decode a data URL into raw bytes."""
    if not data_url or not isinstance(data_url, str):
        return None

    if not data_url.startswith('data:') or ',' not in data_url:
        return None

    try:
        _, encoded = data_url.split(',', 1)
    except ValueError:
        return None

    try:
        return base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None


def load_master_template_pdf(template_type="acord25"):
    """Load master template PDF bytes for the given template type."""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        row = None
        try:
            cur.execute(
                '''
                SELECT id, template_name, template_type, storage_path, pdf_blob
                FROM master_templates
                WHERE LOWER(template_type) = %s
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                ''',
                (template_type.lower(),)
            )
            row = cur.fetchone()
        except psycopg2.errors.UndefinedColumn:
            conn.rollback()
            cur.execute(
                '''
                SELECT id, template_name, template_type, storage_path
                FROM master_templates
                WHERE LOWER(template_type) = %s
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                ''',
                (template_type.lower(),)
            )
            row = cur.fetchone()
            if row is not None and not isinstance(row, dict):
                row = dict(row)
            if row is not None:
                row['pdf_blob'] = None

        if not row:
            return None, None, None, None, None

        template = dict(row) if not isinstance(row, dict) else row
        template_id = template.get('id')
        template_name = template.get('template_name') or template_type.upper()
        template_type_value = (template.get('template_type') or template_type).lower()
        storage_path = template.get('storage_path') or ''
        pdf_blob = template.get('pdf_blob')

        pdf_content = None
        if pdf_blob:
            try:
                pdf_content = bytes(pdf_blob)
            except (TypeError, ValueError):
                pdf_content = pdf_blob

        if not pdf_content:
            local_file = resolve_local_template_file(template_type_value, storage_path)
            if local_file and local_file.exists():
                pdf_content = local_file.read_bytes()

        return template_id, template_name, pdf_blob, storage_path, pdf_content
    except Exception as error:
        print(f"Error loading master template '{template_type}': {error}")
        return None, None, None, None, None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def refresh_master_template_from_local(template_type, template_name=None, force=False):
    """Replace stored master template PDF with the local copy."""
    if not PSYCOPG2_AVAILABLE:
        raise RuntimeError("psycopg2 not available; cannot refresh master templates.")

    if not template_type:
        raise ValueError("template_type is required")

    template_type_key = str(template_type).lower()
    template_config = MASTER_TEMPLATE_CONFIG.get(template_type_key, {})
    local_filename = template_config.get('filename') or LOCAL_TEMPLATE_FILES.get(template_type_key)
    if not local_filename:
        raise ValueError(f"No local template mapping found for '{template_type}'")

    local_path = LOCAL_TEMPLATE_DIR / local_filename
    if not local_path.exists():
        raise FileNotFoundError(f"Local template file not found: {local_path}")

    pdf_bytes = local_path.read_bytes()
    file_size = len(pdf_bytes)
    storage_path = f"local://{local_path.name}"
    default_template_name = template_config.get('display_name')
    target_template_name = template_name or default_template_name or template_type_key.upper()
    extracted_fields = extract_form_fields_from_pdf_bytes(pdf_bytes)
    form_fields_payload = enrich_form_fields_payload(
        {'fields': extracted_fields or []},
        method='local_template_refresh'
    )

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        pdf_blob_supported = ensure_pdf_blob_column(cur)
        select_columns = (
            'id, template_name, template_type, storage_path, file_size, pdf_blob'
            if pdf_blob_supported
            else 'id, template_name, template_type, storage_path, file_size, NULL::BYTEA AS pdf_blob'
        )

        base_select_sql = f''' 
            SELECT {select_columns}
            FROM master_templates
            WHERE LOWER(template_type) = %s
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
        '''

        cur.execute(base_select_sql, (template_type_key,))
        existing = cur.fetchone()

        if not existing and target_template_name:
            select_by_name = f'''
                SELECT {select_columns}
                FROM master_templates
                WHERE LOWER(template_name) = %s
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT 1
            '''
            cur.execute(select_by_name, (target_template_name.lower(),))
            existing = cur.fetchone()

        target_id = None
        operation = 'inserted'
        if existing:
            existing_dict = dict(existing) if not isinstance(existing, dict) else existing
            target_id = existing_dict.get('id')
            existing_name = existing_dict.get('template_name')
            existing_size = existing_dict.get('file_size')
            existing_blob = existing_dict.get('pdf_blob') if pdf_blob_supported else None
            existing_bytes = None
            if pdf_blob_supported and existing_blob is not None:
                try:
                    existing_bytes = bytes(existing_blob)
                except (TypeError, ValueError):
                    existing_bytes = existing_blob

            same_pdf_bytes = pdf_blob_supported and existing_bytes == pdf_bytes

            if not force and same_pdf_bytes and existing_name == target_template_name and existing_size == file_size:
                return {
                    'updated_rows': 0,
                    'skipped': True,
                    'template_id': target_id,
                    'template_type': template_type_key,
                    'template_name': target_template_name,
                    'file_size': file_size,
                    'storage_path': storage_path
                }

            if pdf_blob_supported:
                update_sql = '''
                    UPDATE master_templates
                    SET template_name = %s,
                        template_type = %s,
                        storage_path = %s,
                        file_size = %s,
                        pdf_blob = %s,
                        form_fields = %s,
                        updated_at = NOW()
                    WHERE id = %s
                '''
                update_params = (
                    target_template_name,
                    template_type_key,
                    storage_path,
                    file_size,
                    psycopg2.Binary(pdf_bytes),
                    Json(form_fields_payload),
                    target_id,
                )
            else:
                update_sql = '''
                    UPDATE master_templates
                    SET template_name = %s,
                        template_type = %s,
                        storage_path = %s,
                        file_size = %s,
                        form_fields = %s,
                        updated_at = NOW()
                    WHERE id = %s
                '''
                update_params = (
                    target_template_name,
                    template_type_key,
                    storage_path,
                    file_size,
                    Json(form_fields_payload),
                    target_id,
                )

            cur.execute(update_sql, update_params)
            updated = cur.rowcount
            operation = 'updated'
        else:
            target_id = str(uuid.uuid4())
            if pdf_blob_supported:
                insert_sql = '''
                    INSERT INTO master_templates (id, template_name, template_type, storage_path, file_size, pdf_blob, form_fields)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                '''
                insert_params = (
                    target_id,
                    target_template_name,
                    template_type_key,
                    storage_path,
                    file_size,
                    psycopg2.Binary(pdf_bytes),
                    Json(form_fields_payload),
                )
            else:
                insert_sql = '''
                    INSERT INTO master_templates (id, template_name, template_type, storage_path, file_size, form_fields)
                    VALUES (%s, %s, %s, %s, %s, %s)
                '''
                insert_params = (
                    target_id,
                    target_template_name,
                    template_type_key,
                    storage_path,
                    file_size,
                    Json(form_fields_payload),
                )

            cur.execute(insert_sql, insert_params)
            updated = cur.rowcount
            operation = 'inserted'

        conn.commit()
        return {
            'updated_rows': updated,
            'skipped': False,
            'operation': operation,
            'template_id': target_id,
            'template_type': template_type_key,
            'template_name': target_template_name,
            'file_size': file_size,
            'storage_path': storage_path
        }
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def refresh_all_templates_from_local(force=False, template_types=None):
    """Refresh every known template from local storage into the database."""
    results = {}
    errors = {}

    allowed_types = set(t.lower() for t in template_types) if template_types else None

    for template_type, config in MASTER_TEMPLATE_CONFIG.items():
        if allowed_types and template_type not in allowed_types:
            continue

        display_name = config.get('display_name')
        try:
            refresh_result = refresh_master_template_from_local(
                template_type,
                template_name=display_name,
                force=force
            )
            results[template_type] = refresh_result
        except Exception as exc:
            errors[template_type] = str(exc)

    return results, errors


def fill_acord25_fields(pdf_bytes, field_values, signature_bytes=None):
    """Fill ACORD 25 PDF fields using PyMuPDF, with checkbox fallbacks via pypdf."""
    if not PYMUPDF_AVAILABLE:
        raise RuntimeError("PyMuPDF (fitz) is required to generate ACORD 25 certificates")

    if not pdf_bytes:
        raise ValueError("Template PDF content is empty")

    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    signature_applied = False
    checkbox_updates = {}
    failed_fields = []
    filled_count = 0
    filled_bytes = None

    try:
        for page_index in range(len(pdf_doc)):
            page = pdf_doc[page_index]
            widgets = list(page.widgets())

            for widget in widgets:
                field_name = widget.field_name
                if not field_name:
                    continue

                normalized_name = field_name.strip()
                value = field_values.get(normalized_name)
                field_type_lower = (widget.field_type_string or '').lower()

                if value is not None:
                    is_checkbox_like = field_type_lower in {'checkbox', 'button', 'btn', 'radiobutton'}

                    # Skip empty strings for non-checkbox fields
                    if not is_checkbox_like and str(value).strip() == '':
                        pass
                    else:
                        try:
                            handled = False

                            if field_type_lower == 'text':
                                text_value = str(value)
                                if text_value.startswith('/') and len(text_value) > 1:
                                    core = text_value[1:].lower()
                                    if core in {'yes', 'on', '1', 'true', 'y'}:
                                        text_value = 'Yes'
                                    elif core in {'no', 'off', '0', 'false', 'n'}:
                                        text_value = 'No'
                                widget.field_value = text_value
                                widget.update()
                                filled_count += 1
                                handled = True

                            elif field_type_lower in {'checkbox', 'button', 'btn'}:
                                if PYPDF_AVAILABLE:
                                    checkbox_updates[field_name] = value
                                else:
                                    pdf_state, field_state = resolve_checkbox_state(value)
                                    try:
                                        widget.field_value = field_state
                                        widget.update()
                                        filled_count += 1
                                    except Exception as checkbox_error:
                                        fallback_state = pdf_state.lstrip('/') if isinstance(pdf_state, str) else field_state
                                        try:
                                            widget.field_value = fallback_state
                                            widget.update()
                                            filled_count += 1
                                        except Exception as fallback_error:
                                            failed_fields.append((normalized_name, f"checkbox update failed: {fallback_error}"))
                                            print(f"Warning: checkbox field '{normalized_name}' fallback failed: {fallback_error}")
                                handled = True

                            elif field_type_lower == 'radiobutton':
                                normalized = str(value).strip().lower()
                                is_checked = normalized in {'true', '1', 'yes', 'on', 'checked', 'x', '/yes', '/on', '/1'}
                                target_states = ['X', 'Yes', '1', 'On'] if is_checked else ['Off', '/Off']
                                applied = False
                                for state in target_states:
                                    try:
                                        widget.field_value = state
                                        widget.update()
                                        filled_count += 1
                                        applied = True
                                        break
                                    except Exception:
                                        continue
                                if not applied:
                                    failed_fields.append((normalized_name, 'radio button state could not be applied'))
                                    print(f"Warning: radio button '{normalized_name}' could not apply state for value '{value}'")
                                handled = True

                            if not handled:
                                widget.field_value = str(value)
                                widget.update()
                                filled_count += 1

                        except Exception as fill_error:
                            failed_fields.append((normalized_name, str(fill_error)))
                            print(f"Warning: failed to set field '{normalized_name}': {fill_error}")

                if (
                    signature_bytes
                    and not signature_applied
                    and normalized_name == 'Producer_AuthorizedRepresentative_Signature_A'
                ):
                    try:
                        rect = widget.rect
                        if rect and rect.get_area() > 0:
                            try:
                                widget.field_value = ''
                                widget.update()
                            except Exception:
                                pass

                            image_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1)
                            page.insert_image(image_rect, stream=signature_bytes, keep_proportion=True)
                            signature_applied = True
                    except Exception as signature_error:
                        print(f"Warning: unable to insert signature image: {signature_error}")

        filled_bytes = pdf_doc.write()
    finally:
        pdf_doc.close()

    if filled_bytes is None:
        raise RuntimeError("Failed to render filled PDF content for ACORD 25 certificate")

    if checkbox_updates and PYPDF_AVAILABLE:
        filled_bytes, checkbox_successes, checkbox_failures = fill_checkboxes_with_pypdf(filled_bytes, checkbox_updates)
        if checkbox_failures:
            for failed_name in checkbox_failures:
                failed_fields.append((failed_name, 'checkbox update failed via pypdf'))
            print(f"Warning: pypdf checkbox updates failed for: {checkbox_failures}")
        if checkbox_successes:
            print(f"Checkbox states applied via pypdf: {checkbox_successes[:5]} (total {len(checkbox_successes)} successes)")

    if failed_fields:
        sample = failed_fields[:5]
        print(f"Checkbox/text fill warnings: {sample}")

    return filled_bytes


def sanitize_filename_component(value, fallback="document"):
    """Create a filesystem-safe component for filenames."""
    if not value:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return cleaned or fallback


def fetch_selected_certificate_holders(normalized_account_id, holder_ids):
    """Return a dictionary of certificate holder rows indexed by ID."""
    if not holder_ids:
        return {}

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        placeholders = ','.join(['%s'] * len(holder_ids))
        query = f"""
            SELECT id, account_id, name, master_remarks, address_line1, address_line2,
                   city, state, postal_code, email, phone
            FROM certificate_holders
            WHERE account_id = %s AND id IN ({placeholders})
            ORDER BY name ASC, created_at DESC
        """
        params = [normalized_account_id] + holder_ids
        cur.execute(query, params)
        rows = cur.fetchall()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    holders_by_id = {}
    for row in rows:
        if not row:
            continue
        if not isinstance(row, dict):
            row = dict(row)
        holder_id = row.get('id')
        if not holder_id:
            continue
        holders_by_id[str(holder_id)] = row
    return holders_by_id


def build_template_base_field_values(normalized_account_id, template_id, template_blob, template_storage_path):
    """Load persisted field values to merge into generated certificates."""
    base_field_values = {}
    if not template_id:
        return base_field_values

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        account_template_values = {}

        try:
            cur.execute(
                '''
                SELECT field_values
                FROM template_data
                WHERE account_id = %s AND template_id = %s
                LIMIT 1
                ''',
                (normalized_account_id, template_id)
            )
            template_data_row = cur.fetchone()
            if template_data_row:
                if not isinstance(template_data_row, dict):
                    template_data_row = dict(template_data_row)
                field_values_raw = template_data_row.get('field_values')
                if isinstance(field_values_raw, str):
                    try:
                        account_template_values = json.loads(field_values_raw) or {}
                    except json.JSONDecodeError:
                        account_template_values = {}
                elif isinstance(field_values_raw, dict):
                    account_template_values = field_values_raw or {}
        except Exception as template_data_error:
            print(f"Warning: unable to load template data for account {normalized_account_id}: {template_data_error}")
            account_template_values = {}

        if isinstance(account_template_values, dict):
            for key, value in account_template_values.items():
                if value is None:
                    continue
                base_field_values[str(key)] = normalize_checkbox_entry(str(key), value)

        if template_blob is None and not template_storage_path:
            try:
                cur.execute(
                    'SELECT form_fields FROM master_templates WHERE id = %s LIMIT 1',
                    (template_id,)
                )
                simple_template_row = cur.fetchone()
                if simple_template_row and not isinstance(simple_template_row, dict):
                    simple_template_row = dict(simple_template_row)
                if simple_template_row and simple_template_row.get('form_fields'):
                    metadata_values = coerce_form_fields_payload(simple_template_row['form_fields']).get('field_values') or {}
                    for key, value in (metadata_values or {}).items():
                        if value is None:
                            continue
                        normalized_value = normalize_checkbox_entry(str(key), value)
                        base_field_values.setdefault(str(key), normalized_value)
            except Exception as template_meta_error:
                print(f"Warning: unable to load template metadata: {template_meta_error}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return base_field_values


def generate_certificate_filename(holder_name, template_label, generation_date):
    """Return a consistent filename for generated certificates."""
    holder_component = sanitize_filename_component(holder_name, fallback='holder')
    template_component = sanitize_filename_component(template_label, fallback='template')
    return f"{holder_component}_{template_component}_{generation_date}.pdf"


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
        return f"<h1>Acords Management System</h1><p>Frontend not available: {str(e)}</p>"

def _serve_index_for_context(account_id=None, owner_id=None):
    """Serve the frontend index.html, including fallback context information if needed."""
    try:
        return send_from_directory(app.static_folder, 'index.html')
    except Exception:
        try:
            return send_from_directory('.', 'index.html')
        except Exception as e:
            owner_row = f"<p>Owner: {owner_id}</p>" if owner_id else ""
            account_row = f"<p>Account: {account_id}</p>" if account_id else ""
            return f"""
            <!DOCTYPE html>
            <html>
            <head><title>Acords Management System</title></head>
            <body>
                <h1>Acords Management System</h1>
                {account_row}
                {owner_row}
                <p>Error: {str(e)}</p>
                <p><a href="/api/health">Check API Health</a></p>
            </body>
            </html>
            """

@app.route("/<account_id>")
def serve_account(account_id):
    """Serve the app for a specific Salesforce Account ID"""
    try:
        # Check if this is a Salesforce Account ID (15 or 18 characters starting with 001)
        if len(account_id) >= 15 and account_id.startswith('001'):
            return _serve_index_for_context(account_id=account_id)
        else:
            return f"Invalid Account ID format: {account_id}", 400
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route("/<account_id>/<owner_id>")
def serve_account_owner(account_id, owner_id):
    """Serve the app for a specific Salesforce Account ID and Owner ID"""
    try:
        if len(account_id) >= 15 and account_id.startswith('001'):
            return _serve_index_for_context(account_id=account_id, owner_id=owner_id)
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
        "message": "Acords Management System is working",
        "timestamp": datetime.utcnow().isoformat(),
        "features": {
            "supabase": SUPABASE_AVAILABLE and supabase is not None,
            "pypdf": PYPDF_AVAILABLE,
            "database": PSYCOPG2_AVAILABLE
        }
    })

@app.route("/api/config")
def get_config():
    """Return client-side configuration (public values only)"""
    return jsonify({
        "adobeClientId": os.environ.get('REACT_APP_ADOBE_CLIENT_ID', '')
    })

@app.route("/api/setup", methods=['POST'])
@require_sf_session
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
            # Run migrations to add new columns
            ensure_generated_certificates_table()
            results['generated_certificates_migration'] = True
        else:
            results['database_schema'] = False

        return jsonify({
            'success': True,
            'message': 'System setup completed',
            'results': results
        })
    except Exception as e:
        print(f"Error saving PDF fields: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route("/api/admin/templates/refresh", methods=['POST'])
@require_sf_session
def refresh_templates_endpoint():
    """Refresh master template PDFs from local storage."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    payload = request.get_json(silent=True) if request.is_json else None
    force = False
    requested_templates = None
    missing_templates = []

    if isinstance(payload, dict):
        force = bool(payload.get('force', False))
        requested = payload.get('templates')
        if requested:
            requested_templates = []
            for entry in requested:
                if entry is None:
                    continue
                key = str(entry).lower()
                if key in MASTER_TEMPLATE_CONFIG:
                    requested_templates.append(key)
                else:
                    missing_templates.append(key)

    results, errors = refresh_all_templates_from_local(force=force, template_types=requested_templates)
    refreshed_count = sum(1 for data in results.values() if not data.get('skipped'))
    status_code = 200 if not errors else 207

    return jsonify({
        'success': len(errors) == 0,
        'force': force,
        'refreshed_count': refreshed_count,
        'requested_templates': requested_templates,
        'missing_templates': missing_templates,
        'results': results,
        'errors': errors
    }), status_code


@app.route("/api/account/<account_id>")
@require_sf_session
def get_account_info(account_id):
    """Get account information for the given Salesforce Account ID"""
    return jsonify({
        "account_id": account_id,
        "message": "Account data will be integrated with Salesforce",
        "status": "ready"
    })

@app.route("/api/account/<account_id>/templates", methods=['GET'])
@require_sf_session
def get_account_templates(account_id):
    """Get all master templates available for the account"""
    try:
        query = '''
            SELECT id, template_name, template_type, form_fields, created_at
            FROM master_templates
            ORDER BY template_name
        '''

        def fetch_templates():
            connection = None
            cursor = None
            try:
                connection = get_db()
                cursor = connection.cursor()
                cursor.execute(query)
                return cursor.fetchall()
            finally:
                if cursor:
                    cursor.close()
                if connection:
                    connection.close()

        templates = fetch_templates()

        existing_types = set()
        for row in templates:
            if not row:
                continue
            template_type_value = (row.get('template_type') or '').strip().lower()
            if template_type_value:
                existing_types.add(template_type_value)

        missing_types = [
            template_key
            for template_key in MASTER_TEMPLATE_CONFIG.keys()
            if template_key not in existing_types
        ]

        if missing_types:
            refresh_all_templates_from_local(force=False, template_types=missing_types)
            templates = fetch_templates()

        template_payloads = []
        final_types = set()
        for row in templates:
            template_data = dict(row)
            template_data['form_fields'] = coerce_form_fields_payload(template_data.get('form_fields'))
            template_type_value = (template_data.get('template_type') or '').strip().lower()
            if template_type_value:
                final_types.add(template_type_value)
            template_payloads.append(template_data)

        remaining_missing_types = [
            template_key
            for template_key in MASTER_TEMPLATE_CONFIG.keys()
            if template_key not in final_types
        ]

        for template_key in remaining_missing_types:
            config = MASTER_TEMPLATE_CONFIG.get(template_key, {})
            placeholder = {
                'id': template_key,
                'template_name': config.get('display_name') or template_key.upper(),
                'template_type': template_key,
                'form_fields': {'fields': []},
                'created_at': None,
                'storage_path': f"local://{config.get('filename')}" if config.get('filename') else None,
                'metadata_source': 'local',
                'missing': True,
            }
            template_payloads.append(placeholder)

        def template_sort_key(item):
            name = str(item.get('template_name') or '')
            template_type_value = str(item.get('template_type') or '')
            for candidate in (name, template_type_value):
                match = re.search(r'(\d+)', candidate)
                if match:
                    return (int(match.group(1)), name.lower())
            return (10**6, name.lower())

        template_payloads.sort(key=template_sort_key)

        return jsonify({
            'success': True,
            'account_id': account_id,
            'templates': template_payloads
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/templates', methods=['GET'])
@require_sf_session
def list_admin_templates():
    """Return the list of known templates and supported mapping scopes."""
    template_entries = [
        {
            'key': key,
            'name': config.get('display_name') or key.upper()
        }
        for key, config in MASTER_TEMPLATE_CONFIG.items()
    ]
    template_entries.sort(key=lambda item: item['name'])
    return jsonify({
        'success': True,
        'templates': template_entries,
        'scopes': sorted(FIELD_MAPPING_SCOPES)
    })


@app.route('/admin/mappings')
def admin_mappings_page():
    """Serve the admin UI for editing field mappings."""
    try:
        return send_from_directory('.', 'admin_mappings.html')
    except Exception as e:
        return f"<h1>Field Mapping Admin</h1><p>Unable to load admin UI: {str(e)}</p>", 500


@app.route('/api/admin/field-mappings', methods=['GET', 'PUT'])
@require_sf_session
def admin_field_mappings():
    """Allow admins to view or edit field mappings for agency/certificate holder scopes."""
    if request.method == 'GET':
        template_key = normalize_template_key(request.args.get('template_key'))
        scope = (request.args.get('scope') or '').strip().lower()
        use_defaults = (request.args.get('use_defaults') or '').lower() in {'1', 'true', 'yes'}
        if scope not in FIELD_MAPPING_SCOPES:
            return jsonify({'success': False, 'error': 'Invalid mapping scope'}), 400
        if use_defaults:
            fields = get_default_field_mapping(template_key, scope)
            return jsonify({
                'success': True,
                'template_key': template_key,
                'scope': scope,
                'fields': fields,
                'source': 'default'
            })
        mapping, source = resolve_field_mapping(template_key, scope, include_source=True)
        return jsonify({
            'success': True,
            'template_key': template_key,
            'scope': scope,
            'fields': mapping or {},
            'source': source
        })

    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    data = request.get_json() or {}
    template_key = normalize_template_key(data.get('template_key'))
    scope = (data.get('scope') or '').strip().lower()
    if scope not in FIELD_MAPPING_SCOPES:
        return jsonify({'success': False, 'error': 'Invalid mapping scope'}), 400
    fields = data.get('fields')
    if not isinstance(fields, dict):
        return jsonify({'success': False, 'error': 'fields must be an object map'}), 400

    normalized_fields = {}
    for key, value in fields.items():
        if key is None:
            continue
        key_str = str(key).strip()
        if not key_str:
            continue
        normalized_fields[key_str] = '' if value is None else str(value)

    save_field_mapping_to_db(
        template_key,
        scope,
        normalized_fields,
        data.get('updated_by')
    )
    return jsonify({
        'success': True,
        'template_key': template_key,
        'scope': scope,
        'fields': normalized_fields,
        'source': 'database'
    })


@app.route("/api/account/<account_id>/certificate-holders", methods=['GET'])
@require_sf_session
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
            SELECT id, account_id, name, master_remarks, address_line1, address_line2, city, state, postal_code, email, phone,
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
@require_sf_session
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
                account_id, name, master_remarks, address_line1, address_line2, city, state, postal_code, email, phone
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        ''', (
            normalized_account_id,
            sanitized.get('name'),
            sanitized.get('master_remarks'),
            sanitized.get('address_line1'),
            sanitized.get('address_line2'),
            sanitized.get('city'),
            sanitized.get('state'),
            sanitized.get('postal_code'),
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
            SELECT id, account_id, name, master_remarks, address_line1, address_line2,
                   city, state, postal_code, email, phone, created_at, updated_at
            FROM certificate_holders
            WHERE account_id = %s AND id = %s
        ''', (normalized_account_id, holder_id))
        row = cur.fetchone()
        return row
    finally:
        cur.close()
        conn.close()


@app.route("/api/account/<account_id>/certificate-holders/<holder_id>", methods=['GET'])
@require_sf_session
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
@require_sf_session
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
                address_line2 = %s,
                city = %s,
                state = %s,
                postal_code = %s,
                email = %s,
                phone = %s,
                updated_at = NOW()
            WHERE account_id = %s AND id = %s
            RETURNING *
        ''', (
            sanitized.get('name'),
            sanitized.get('master_remarks'),
            sanitized.get('address_line1'),
            sanitized.get('address_line2'),
            sanitized.get('city'),
            sanitized.get('state'),
            sanitized.get('postal_code'),
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
@require_sf_session
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


# ============================================================================
# AGENCY SETTINGS ENDPOINTS
# ============================================================================

def format_agency_settings(record):
    """Format agency settings record for JSON response."""
    if not record:
        return None
    return {
        'id': str(record['id']) if record.get('id') else None,
        'account_id': record.get('account_id'),
        'name': record.get('name'),
        'street': record.get('street'),
        'suite': record.get('suite'),
        'city': record.get('city'),
        'state': record.get('state'),
        'zip': record.get('zip'),
        'phone': record.get('phone'),
        'fax': record.get('fax'),
        'email': record.get('email'),
        'producerName': record.get('producer_name'),
        'producerPhone': record.get('producer_phone'),
        'producerEmail': record.get('producer_email'),
        'signatureImage': record.get('signature_image'),
        'created_at': record['created_at'].isoformat() if record.get('created_at') else None,
        'updated_at': record['updated_at'].isoformat() if record.get('updated_at') else None,
    }


@app.route("/api/account/<account_id>/agency-settings", methods=['GET'])
@require_sf_session
def get_agency_settings(account_id):
    """Get agency settings for an account."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT * FROM agency_settings WHERE account_id = %s
        ''', (normalized_account_id,))
        record = cur.fetchone()

        return jsonify({
            'success': True,
            'agency_settings': format_agency_settings(record) if record else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/account/<account_id>/agency-settings", methods=['POST', 'PUT'])
@require_sf_session
def save_agency_settings(account_id):
    """Create or update agency settings for an account."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    data = request.get_json() or {}

    # Sanitize input - accept both camelCase and snake_case
    sanitized = {
        'name': normalize_string(data.get('name'), 255),
        'street': normalize_string(data.get('street'), 255),
        'suite': normalize_string(data.get('suite'), 100),
        'city': normalize_string(data.get('city'), 120),
        'state': normalize_string(data.get('state'), 2),
        'zip': normalize_string(data.get('zip'), 20),
        'phone': normalize_string(data.get('phone'), 50),
        'fax': normalize_string(data.get('fax'), 50),
        'email': normalize_string(data.get('email'), 255),
        'producer_name': normalize_string(data.get('producer_name') or data.get('producerName'), 255),
        'producer_phone': normalize_string(data.get('producer_phone') or data.get('producerPhone'), 50),
        'producer_email': normalize_string(data.get('producer_email') or data.get('producerEmail'), 255),
        'signature_image': data.get('signature_image') or data.get('signatureImage'),  # Base64 image, can be large
    }

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        # Upsert - insert or update on conflict
        cur.execute('''
            INSERT INTO agency_settings (account_id, name, street, suite, city, state, zip, phone, fax, email, producer_name, producer_phone, producer_email, signature_image)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id) DO UPDATE SET
                name = EXCLUDED.name,
                street = EXCLUDED.street,
                suite = EXCLUDED.suite,
                city = EXCLUDED.city,
                state = EXCLUDED.state,
                zip = EXCLUDED.zip,
                phone = EXCLUDED.phone,
                fax = EXCLUDED.fax,
                email = EXCLUDED.email,
                producer_name = EXCLUDED.producer_name,
                producer_phone = EXCLUDED.producer_phone,
                producer_email = EXCLUDED.producer_email,
                signature_image = EXCLUDED.signature_image,
                updated_at = NOW()
            RETURNING *
        ''', (
            normalized_account_id,
            sanitized.get('name'),
            sanitized.get('street'),
            sanitized.get('suite'),
            sanitized.get('city'),
            sanitized.get('state'),
            sanitized.get('zip'),
            sanitized.get('phone'),
            sanitized.get('fax'),
            sanitized.get('email'),
            sanitized.get('producer_name'),
            sanitized.get('producer_phone'),
            sanitized.get('producer_email'),
            sanitized.get('signature_image'),
        ))
        record = cur.fetchone()
        conn.commit()

        return jsonify({
            'success': True,
            'agency_settings': format_agency_settings(record)
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


# ============================================================================
# NAMED INSURED (FROM SUPABASE) ENDPOINTS
# ============================================================================

def fetch_named_insured_from_supabase(sf_account_id):
    """
    Fetch Named Insured data from Supabase accounts table by sf_id.
    Returns mapped field values for PDF injection.
    """
    if not SUPABASE_AVAILABLE or not supabase:
        return None, 'Supabase not configured'

    try:
        # Salesforce IDs can be 15 or 18 chars - try both formats
        sf_id_15 = sf_account_id[:15] if len(sf_account_id) >= 15 else sf_account_id
        sf_id_18 = sf_account_id if len(sf_account_id) == 18 else None

        print(f"[Supabase] Looking for sf_id: {sf_account_id}")
        print(f"[Supabase] Also trying 15-char version: {sf_id_15}")

        # Query Supabase accounts table by sf_id (Salesforce Account ID)
        # Try exact match first
        response = supabase.table('accounts').select('*').eq('sf_id', sf_account_id).execute()

        # If no match, try 15-char version
        if (not response.data or len(response.data) == 0) and sf_id_15 != sf_account_id:
            print(f"[Supabase] No match for 18-char, trying 15-char: {sf_id_15}")
            response = supabase.table('accounts').select('*').eq('sf_id', sf_id_15).execute()

        # If still no match, try case-insensitive with ilike
        if not response.data or len(response.data) == 0:
            print(f"[Supabase] No exact match, trying ilike query")
            response = supabase.table('accounts').select('*').ilike('sf_id', sf_account_id).execute()

        if not response.data or len(response.data) == 0:
            # Debug: show what sf_ids exist (first 5)
            try:
                all_accounts = supabase.table('accounts').select('sf_id').limit(5).execute()
                existing_ids = [a.get('sf_id') for a in (all_accounts.data or [])]
                print(f"[Supabase] Sample sf_ids in table: {existing_ids}")
            except Exception as debug_err:
                print(f"[Supabase] Could not fetch sample sf_ids: {debug_err}")
            return None, f'Account not found in Supabase for sf_id: {sf_account_id}'

        account = response.data[0]

        # Map Supabase accounts columns to Named Insured PDF fields
        named_insured = {
            'name': account.get('name'),
            'address_line1': account.get('billing_street'),
            'address_line2': None,  # No separate line2 in Supabase
            'city': account.get('billing_city'),
            'state': account.get('billing_state'),
            'postal_code': account.get('billing_zip'),
            'email': account.get('primary_email'),
            'phone': account.get('phone'),
            'supabase_id': account.get('id'),
        }

        return named_insured, None

    except Exception as e:
        return None, str(e)


def get_named_insured_field_values(sf_account_id, template_key):
    """
    Fetch Named Insured from Supabase and map to PDF field names.
    Returns dict of {pdf_field_name: value} for injection.
    """
    named_insured, error = fetch_named_insured_from_supabase(sf_account_id)
    if not named_insured:
        return {}, error

    field_map = get_named_insured_field_map(template_key)
    field_values = {}

    source_to_value = {
        'name': named_insured.get('name') or '',
        'address_line1': named_insured.get('address_line1') or '',
        'address_line2': named_insured.get('address_line2') or '',
        'city': named_insured.get('city') or '',
        'state': named_insured.get('state') or '',
        'postal_code': named_insured.get('postal_code') or '',
        'email': named_insured.get('email') or '',
        'phone': named_insured.get('phone') or '',
    }

    for source_key, target_field in field_map.items():
        if target_field and source_to_value.get(source_key):
            field_values[target_field] = source_to_value[source_key]

    return field_values, None


@app.route("/api/account/<account_id>/named-insured", methods=['GET'])
@require_sf_session
def get_named_insured(account_id):
    """
    Fetch Named Insured data from Supabase accounts table.
    Matches the URL account_id to sf_id in Supabase.
    """
    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    named_insured, error = fetch_named_insured_from_supabase(normalized_account_id)

    if error:
        return jsonify({
            'success': False,
            'error': error,
            'named_insured': None
        }), 404 if 'not found' in error.lower() else 500

    return jsonify({
        'success': True,
        'named_insured': named_insured
    })


@app.route("/api/account/<account_id>/named-insured/field-values/<template_key>", methods=['GET'])
@require_sf_session
def get_named_insured_for_template(account_id, template_key):
    """
    Get Named Insured field values mapped to specific template PDF fields.
    Used for injecting into PDF edit popup.
    """
    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    field_values, error = get_named_insured_field_values(normalized_account_id, template_key)

    if error and not field_values:
        return jsonify({
            'success': False,
            'error': error,
            'field_values': {}
        }), 404 if 'not found' in error.lower() else 500

    return jsonify({
        'success': True,
        'field_values': field_values,
        'template_key': template_key
    })


@app.route("/api/account/<account_id>/prefill-data/<template_key>", methods=['GET'])
@require_sf_session
def get_prefill_data(account_id, template_key):
    """
    Get all prefill data for PDF edit popup: Agency Settings + Named Insured.
    This is the main endpoint to call when opening a PDF for editing.
    """
    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    result = {
        'success': True,
        'account_id': normalized_account_id,
        'template_key': template_key,
        'agency_field_values': {},
        'named_insured_field_values': {},
        'errors': []
    }

    # Fetch Agency Settings from local DB
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM agency_settings WHERE account_id = %s', (normalized_account_id,))
        agency_record = cur.fetchone()
        cur.close()
        conn.close()

        if agency_record:
            agency_settings = format_agency_settings(agency_record)
            agency_field_map = resolve_field_mapping(template_key, 'agency')
            if agency_field_map and agency_settings:
                for source_key, target_field in agency_field_map.items():
                    if target_field:
                        value = agency_settings.get(source_key)
                        if value:
                            result['agency_field_values'][target_field] = value
    except Exception as e:
        result['errors'].append(f'Agency settings error: {str(e)}')

    # Fetch Named Insured from Supabase
    named_insured_values, ni_error = get_named_insured_field_values(normalized_account_id, template_key)
    if named_insured_values:
        result['named_insured_field_values'] = named_insured_values
    if ni_error:
        result['errors'].append(f'Named Insured: {ni_error}')

    # Combine all field values for easy injection
    result['combined_field_values'] = {
        **result['agency_field_values'],
        **result['named_insured_field_values']
    }

    return jsonify(result)


def process_certificate_generation_request(account_id, payload, default_template_keys=None):
    """Core generation logic shared across certificate generation endpoints."""
    if not PSYCOPG2_AVAILABLE:
        return database_not_configured_response()

    if not PYMUPDF_AVAILABLE:
        return jsonify({'success': False, 'error': 'PDF generation requires PyMuPDF'}), 503

    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    payload = payload or {}

    holder_ids_raw = payload.get('holder_ids') or []
    if not isinstance(holder_ids_raw, (list, tuple)):
        return jsonify({'success': False, 'error': 'holder_ids must be a list'}), 400

    holder_ids = []
    holder_id_keys = set()
    for value in holder_ids_raw:
        try:
            holder_uuid = uuid.UUID(str(value).strip())
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'holder_ids must contain valid UUIDs'}), 400
        holder_key = str(holder_uuid)
        if holder_key in holder_id_keys:
            continue
        holder_ids.append(holder_key)
        holder_id_keys.add(holder_key)

    if not holder_ids:
        return jsonify({'success': False, 'error': 'No certificate holders selected'}), 400

    template_keys_raw = payload.get('template_keys')
    if isinstance(template_keys_raw, str):
        template_keys_raw = [template_keys_raw]
    elif template_keys_raw and not isinstance(template_keys_raw, (list, tuple, set)):
        template_keys_raw = [template_keys_raw]
    if not template_keys_raw:
        single_template = payload.get('template_key')
        if single_template:
            template_keys_raw = [single_template]
    if not template_keys_raw and default_template_keys:
        template_keys_raw = list(default_template_keys)

    template_keys = []
    seen_template_keys = set()
    for entry in template_keys_raw or []:
        normalized_template_key = str(entry or '').strip().lower()
        if not normalized_template_key or normalized_template_key in seen_template_keys:
            continue
        template_keys.append(normalized_template_key)
        seen_template_keys.add(normalized_template_key)

    if not template_keys:
        return jsonify({'success': False, 'error': 'No templates selected'}), 400

    # Fetch agency settings from database (more reliable than frontend payload)
    agency_settings = payload.get('agency_settings') or {}
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT name, street, suite, city, state, zip, phone, fax, email,
                   producer_name, producer_phone, producer_email, signature_image
            FROM agency_settings
            WHERE account_id = %s
        ''', (normalized_account_id,))
        db_agency_record = cur.fetchone()
        cur.close()
        conn.close()
        if db_agency_record:
            # Merge database settings with any frontend overrides
            db_settings = format_agency_settings(db_agency_record)
            print(f"[Generate] Loaded agency settings from DB: name={db_settings.get('name')}, producerName={db_settings.get('producerName')}, producerPhone={db_settings.get('producerPhone')}")
            # Database settings take precedence, but frontend can fill gaps
            for key, value in db_settings.items():
                if value and (not agency_settings.get(key)):
                    agency_settings[key] = value
    except Exception as agency_db_error:
        print(f"Warning: Could not fetch agency settings from database: {agency_db_error}")

    signature_data_url = agency_settings.get('signatureDataUrl') or agency_settings.get('signature_data_url') or agency_settings.get('signatureImage')
    signature_bytes = decode_data_url(signature_data_url) if signature_data_url else None
    signature_bytes = None  # Use text-based signature representation

    # Fetch Named Insured data from Supabase for injection
    named_insured_data = None
    try:
        named_insured_data, ni_error = fetch_named_insured_from_supabase(normalized_account_id)
        if ni_error:
            print(f"Warning: Could not fetch Named Insured from Supabase: {ni_error}")
    except Exception as ni_exception:
        print(f"Warning: Named Insured fetch error: {ni_exception}")
        named_insured_data = None

    try:
        holders_by_id = fetch_selected_certificate_holders(normalized_account_id, holder_ids)
    except Exception as db_error:
        return jsonify({'success': False, 'error': str(db_error)}), 500

    if not holders_by_id:
        return jsonify({'success': False, 'error': 'Certificate holders not found'}), 404

    missing_ids = [hid for hid in holder_ids if hid not in holders_by_id]
    if missing_ids:
        return jsonify({'success': False, 'error': f'Certificate holders not found: {missing_ids}'}), 404

    generation_date = datetime.utcnow().strftime('%Y-%m-%d')
    generated_files = []

    for template_key in template_keys:
        template_id, template_name, template_blob, template_storage_path, template_bytes = load_master_template_pdf(template_key)
        if not template_bytes:
            local_template = resolve_local_template_file(template_key, None)
            if local_template and local_template.exists():
                template_bytes = local_template.read_bytes()
        if not template_bytes:
            display_name = MASTER_TEMPLATE_CONFIG.get(template_key, {}).get('display_name') or template_key.upper()
            return jsonify({'success': False, 'error': f'{display_name} template is not available'}), 503

        base_field_values = build_template_base_field_values(normalized_account_id, template_id, template_blob, template_storage_path)
        holder_field_map = get_certificate_holder_field_map(template_key)
        agency_field_map = resolve_field_mapping(template_key, 'agency')
        template_label = template_name or MASTER_TEMPLATE_CONFIG.get(template_key, {}).get('display_name') or template_key.upper()

        for holder_key in holder_ids:
            holder_row = holders_by_id.get(holder_key)
            if not holder_row:
                continue
            holder = format_certificate_holder(holder_row)
            if not holder:
                continue

            holder_source_values = {
                'name': holder.get('name') or '',
                'address_line1': holder.get('address_line1') or '',
                'address_line2': holder.get('address_line2') or '',
                'city': holder.get('city') or '',
                'state': holder.get('state') or '',
                'postal_code': holder.get('postal_code') or '',
                'master_remarks': holder.get('master_remarks') or ''
            }

            holder_field_values = {}
            for source_key, target_field in holder_field_map.items():
                if not target_field:
                    continue
                value = holder_source_values.get(source_key)
                if value is None:
                    continue
                holder_field_values[target_field] = value

            final_field_values = {}
            if isinstance(base_field_values, dict):
                for key, value in base_field_values.items():
                    if value is None:
                        continue
                    final_field_values[str(key)] = value

            for key, value in holder_field_values.items():
                normalized_value = normalize_checkbox_entry(key, value)
                base_val = final_field_values.get(key)
                if base_val is None or str(base_val).strip() == '':
                    if normalized_value not in (None, ''):
                        final_field_values[key] = normalized_value
                elif normalized_value not in (None, ''):
                    final_field_values[key] = normalized_value

            for key, value in holder_field_values.items():
                if key not in final_field_values:
                    final_field_values[key] = normalize_checkbox_entry(key, value)

            if agency_field_map and isinstance(agency_settings, dict):
                for source_key, target_field in agency_field_map.items():
                    if not target_field:
                        continue
                    agency_value = agency_settings.get(source_key)
                    if agency_value in (None, ''):
                        continue
                    normalized_agency_value = normalize_checkbox_entry(target_field, agency_value)
                    existing = final_field_values.get(target_field)
                    if existing is None or str(existing).strip() == '':
                        final_field_values[target_field] = normalized_agency_value

            # Apply Named Insured data from Supabase
            if named_insured_data:
                named_insured_field_map = get_named_insured_field_map(template_key)
                named_insured_source_values = {
                    'name': named_insured_data.get('name') or '',
                    'address_line1': named_insured_data.get('address_line1') or '',
                    'address_line2': named_insured_data.get('address_line2') or '',
                    'city': named_insured_data.get('city') or '',
                    'state': named_insured_data.get('state') or '',
                    'postal_code': named_insured_data.get('postal_code') or '',
                    'email': named_insured_data.get('email') or '',
                    'phone': named_insured_data.get('phone') or '',
                }
                for source_key, target_field in named_insured_field_map.items():
                    if not target_field:
                        continue
                    ni_value = named_insured_source_values.get(source_key)
                    if ni_value in (None, ''):
                        continue
                    normalized_ni_value = normalize_checkbox_entry(target_field, ni_value)
                    existing = final_field_values.get(target_field)
                    if existing is None or str(existing).strip() == '':
                        final_field_values[target_field] = normalized_ni_value

            for key in list(final_field_values.keys()):
                final_field_values[key] = normalize_checkbox_entry(key, final_field_values[key])

            signature_text = (
                agency_settings.get('signatureText')
                or agency_settings.get('signature_text')
                or agency_settings.get('name')
                or ''
            )
            if signature_text:
                final_field_values['Producer_AuthorizedRepresentative_Signature_A'] = signature_text

            try:
                filled_pdf = fill_acord25_fields(template_bytes, final_field_values, signature_bytes=signature_bytes)
            except Exception as fill_error:
                display_name = template_label or template_key.upper()
                return jsonify({
                    'success': False,
                    'error': f'Failed to generate PDF for {holder.get("name")} ({display_name}): {fill_error}'
                }), 500

            filename = generate_certificate_filename(holder.get('name'), template_label, generation_date)
            generated_files.append({
                'filename': filename,
                'pdf_bytes': filled_pdf,
                'template_id': template_id,
                'template_key': template_key,
                'holder_id': holder_key
            })

    if not generated_files:
        return jsonify({'success': False, 'error': 'No certificates generated'}), 500

    response_stream = None
    response_mimetype = 'application/zip'
    response_filename = f"Certificates_{sanitize_filename_component(normalized_account_id)}_{generation_date}.zip"

    if len(generated_files) == 1:
        single_entry = generated_files[0]
        response_stream = io.BytesIO(single_entry['pdf_bytes'])
        response_stream.seek(0)
        response_mimetype = 'application/pdf'
        response_filename = single_entry['filename']
    else:
        response_stream = io.BytesIO()
        with zipfile.ZipFile(response_stream, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:
            for entry in generated_files:
                zip_file.writestr(entry['filename'], entry['pdf_bytes'])
        response_stream.seek(0)

    ensure_generated_certificates_table()

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        for entry in generated_files:
            holder_key = entry.get('holder_id')
            filename = entry.get('filename')
            pdf_bytes = entry.get('pdf_bytes')
            template_id = entry.get('template_id')
            local_path = None
            if LOCAL_TEMPLATE_DIR.exists():
                account_dir = LOCAL_TEMPLATE_DIR.parent / 'generated' / sanitize_filename_component(normalized_account_id)
                account_dir.mkdir(parents=True, exist_ok=True)
                file_path = account_dir / filename
                file_path.write_bytes(pdf_bytes)
                local_path = str(file_path.relative_to(LOCAL_TEMPLATE_DIR.parent))

            print(f"[Generated Certs INSERT] account={normalized_account_id}, holder={holder_key}, template={template_id}, filename={filename}")
            cur.execute(
                '''
                INSERT INTO generated_certificates (
                    id, account_id, template_id, certificate_holder_id, filename, storage_path, pdf_blob, generated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                ''',
                (
                    str(uuid.uuid4()),
                    normalized_account_id,
                    template_id,
                    holder_key,
                    filename,
                    local_path,
                    psycopg2.Binary(pdf_bytes) if PSYCOPG2_AVAILABLE else None
                )
            )
            inserted_id = cur.fetchone()
            print(f"[Generated Certs INSERT] Successfully inserted ID: {inserted_id}")
        conn.commit()
        print(f"[Generated Certs INSERT] Committed {len(generated_files)} certificates to database")
    except Exception as store_error:
        print(f"ERROR: unable to persist generated certificates: {store_error}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    response_stream.seek(0)
    return send_file(
        response_stream,
        mimetype=response_mimetype,
        as_attachment=True,
        download_name=response_filename
    )


@app.route("/api/account/<account_id>/certificate-holders/generated", methods=['POST'])
@require_sf_session
def generate_certificates(account_id):
    """Generate certificates for selected holders and templates."""
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}
    return process_certificate_generation_request(account_id, payload, default_template_keys=None)


@app.route("/api/account/<account_id>/certificate-holders/generated/acord25", methods=['POST'])
@require_sf_session
def generate_acord25_certificates(account_id):
    """Preserve backwards-compatible ACORD 25 generation endpoint."""
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}
    if 'template_keys' not in payload and 'template_key' not in payload:
        payload = dict(payload)
        payload['template_keys'] = ['acord25']
    return process_certificate_generation_request(account_id, payload, default_template_keys=['acord25'])


@app.route("/api/account/<account_id>/generated-certificates", methods=['GET'])
@require_sf_session
def list_generated_certificates(account_id):
    """List all generated certificates for an account with history."""
    normalized_account_id = normalize_account_id(account_id)
    if not normalized_account_id:
        return jsonify({'success': False, 'error': 'Invalid account ID'}), 400

    if not PSYCOPG2_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check which columns exist in the table
        cur.execute('''
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'generated_certificates'
        ''')
        existing_columns = set(row['column_name'] for row in cur.fetchall())
        print(f"[Generated Certs] Existing columns: {existing_columns}")

        has_filename = 'filename' in existing_columns
        has_certificate_name = 'certificate_name' in existing_columns
        has_holder_id = 'certificate_holder_id' in existing_columns
        has_pdf_blob = 'pdf_blob' in existing_columns
        print(f"[Generated Certs] has_filename={has_filename}, has_certificate_name={has_certificate_name}, has_holder_id={has_holder_id}, has_pdf_blob={has_pdf_blob}")

        # Build dynamic SELECT based on available columns
        if has_filename:
            filename_expr = 'gc.filename'
        elif has_certificate_name:
            filename_expr = 'gc.certificate_name as filename'
        else:
            filename_expr = "NULL as filename"

        if has_holder_id:
            # Query with holder join
            cur.execute(f'''
                SELECT
                    gc.id,
                    gc.account_id,
                    gc.template_id,
                    gc.certificate_holder_id,
                    {filename_expr},
                    gc.generated_at,
                    ch.name as holder_name,
                    mt.template_name,
                    mt.template_type
                FROM generated_certificates gc
                LEFT JOIN certificate_holders ch ON gc.certificate_holder_id::text = ch.id::text
                LEFT JOIN master_templates mt ON gc.template_id = mt.id
                WHERE gc.account_id = %s OR gc.account_id = %s
                ORDER BY gc.generated_at DESC
            ''', (normalized_account_id, account_id))
        else:
            # Query without holder join
            cur.execute(f'''
                SELECT
                    gc.id,
                    gc.account_id,
                    gc.template_id,
                    NULL as certificate_holder_id,
                    {filename_expr},
                    gc.generated_at,
                    NULL as holder_name,
                    mt.template_name,
                    mt.template_type
                FROM generated_certificates gc
                LEFT JOIN master_templates mt ON gc.template_id = mt.id
                WHERE gc.account_id = %s OR gc.account_id = %s
                ORDER BY gc.generated_at DESC
            ''', (normalized_account_id, account_id))

        certificates = cur.fetchall()
        print(f"[Generated Certs] Query returned {len(certificates)} certificates for account_id={account_id}, normalized={normalized_account_id}")

        # Convert to list of dicts and format dates
        result = []
        for cert in certificates:
            cert_dict = dict(cert)
            if cert_dict.get('generated_at'):
                cert_dict['generated_at'] = cert_dict['generated_at'].isoformat()
            # Extract holder name from filename if not available
            if not cert_dict.get('holder_name') and cert_dict.get('filename'):
                # Filename format: holdername_templatename_date.pdf
                parts = cert_dict['filename'].rsplit('_', 2)
                if len(parts) >= 2:
                    cert_dict['holder_name'] = parts[0].replace('_', ' ')
            # Flag whether PDF blob is available for viewing
            cert_dict['has_pdf'] = has_pdf_blob
            result.append(cert_dict)

        return jsonify({
            'success': True,
            'certificates': result,
            'count': len(result)
        })

    except Exception as e:
        print(f"Error listing generated certificates: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/account/<account_id>/generated-certificates/<certificate_id>", methods=['GET'])
@require_sf_session
def get_generated_certificate(account_id, certificate_id):
    """Get a specific generated certificate PDF."""
    normalized_account_id = normalize_account_id(account_id)
    if not normalized_account_id:
        return jsonify({'success': False, 'error': 'Invalid account ID'}), 400

    if not PSYCOPG2_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check which columns exist
        cur.execute('''
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'generated_certificates'
        ''')
        existing_columns = set(row['column_name'] for row in cur.fetchall())

        has_filename = 'filename' in existing_columns
        has_certificate_name = 'certificate_name' in existing_columns
        has_pdf_blob = 'pdf_blob' in existing_columns

        if not has_pdf_blob:
            return jsonify({'success': False, 'error': 'PDF storage not available. Certificates were generated before PDF blob storage was enabled.'}), 404

        # Build filename expression
        if has_filename:
            filename_expr = 'gc.filename'
        elif has_certificate_name:
            filename_expr = 'gc.certificate_name as filename'
        else:
            filename_expr = "NULL as filename"

        cur.execute(f'''
            SELECT
                gc.id,
                {filename_expr},
                gc.pdf_blob,
                gc.generated_at,
                mt.template_name
            FROM generated_certificates gc
            LEFT JOIN master_templates mt ON gc.template_id = mt.id
            WHERE gc.id = %s AND (gc.account_id = %s OR gc.account_id = %s)
        ''', (certificate_id, normalized_account_id, account_id))

        cert = cur.fetchone()

        if not cert:
            return jsonify({'success': False, 'error': 'Certificate not found'}), 404

        pdf_blob = cert.get('pdf_blob')
        if not pdf_blob:
            return jsonify({'success': False, 'error': 'PDF data not available for this certificate'}), 404

        # Convert memoryview to bytes if needed
        try:
            pdf_bytes = bytes(pdf_blob)
        except (TypeError, ValueError):
            pdf_bytes = pdf_blob

        filename = cert.get('filename') or 'certificate.pdf'

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=filename
        )

    except Exception as e:
        print(f"Error getting generated certificate: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/account/<account_id>/generated-certificates/<certificate_id>/download", methods=['GET'])
@require_sf_session
def download_generated_certificate(account_id, certificate_id):
    """Download a specific generated certificate PDF."""
    normalized_account_id = normalize_account_id(account_id)
    if not normalized_account_id:
        return jsonify({'success': False, 'error': 'Invalid account ID'}), 400

    if not PSYCOPG2_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check which columns exist
        cur.execute('''
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'generated_certificates'
        ''')
        existing_columns = set(row['column_name'] for row in cur.fetchall())

        has_filename = 'filename' in existing_columns
        has_certificate_name = 'certificate_name' in existing_columns
        has_pdf_blob = 'pdf_blob' in existing_columns

        if not has_pdf_blob:
            return jsonify({'success': False, 'error': 'PDF storage not available'}), 404

        # Build filename expression
        if has_filename:
            filename_expr = 'gc.filename'
        elif has_certificate_name:
            filename_expr = 'gc.certificate_name as filename'
        else:
            filename_expr = "NULL as filename"

        cur.execute(f'''
            SELECT {filename_expr}, gc.pdf_blob
            FROM generated_certificates gc
            WHERE gc.id = %s AND (gc.account_id = %s OR gc.account_id = %s)
        ''', (certificate_id, normalized_account_id, account_id))

        cert = cur.fetchone()

        if not cert:
            return jsonify({'success': False, 'error': 'Certificate not found'}), 404

        pdf_blob = cert.get('pdf_blob')
        if not pdf_blob:
            return jsonify({'success': False, 'error': 'PDF data not available'}), 404

        try:
            pdf_bytes = bytes(pdf_blob)
        except (TypeError, ValueError):
            pdf_bytes = pdf_blob

        filename = cert.get('filename') or 'certificate.pdf'

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        print(f"Error downloading certificate: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/provision-pdf", methods=['POST'])
@require_sf_session
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
@require_sf_session
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
@require_sf_session
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


def is_checkbox_field_name(field_name):
    """Best-effort detection for checkbox-type PDF fields based on name."""
    if not field_name:
        return False
    field_lower = str(field_name).strip().lower()
    if field_lower.endswith('text'):
        return False
    checkbox_tokens = {'indicator', 'checkbox', 'check', 'box'}
    return any(token in field_lower for token in checkbox_tokens)


def normalize_checkbox_value(value):
    """Normalize truthy/falsy inputs to PDF checkbox states."""
    if value is None:
        return '/Off'
    normalized = str(value).strip().lower()
    if normalized in {'/yes', 'yes', 'true', '1', 'on', 'y', 'checked', 'x'}:
        return '/Yes'
    if normalized in {'/off', 'no', 'false', '0', 'off', 'n', ''}:
        return '/Off'
    return '/Yes'


def normalize_checkbox_entry(field_name, value):
    """Return normalized checkbox value when the PDF field name looks like a checkbox."""
    if is_checkbox_field_name(field_name):
        return normalize_checkbox_value(value)
    return value








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


def _replace_pdf_blob_column(sql):
    placeholder = '__PDF_BLOB_PLACEHOLDER__'
    temp = sql.replace('mt.pdf_blob', placeholder).replace('pdf_blob', placeholder)
    return temp.replace(placeholder, 'NULL::BYTEA AS pdf_blob')


def execute_with_optional_pdf_blob(cur, sql, params=None):
    """
    Execute a query that might reference mt.pdf_blob, even if the column is missing.
    Rewrites the query to return a NULL placeholder when the column does not exist.
    """
    global PDF_BLOB_COLUMN_AVAILABLE
    if cur is None:
        return None

    if params is None:
        params = []

    if not PSYCOPG2_AVAILABLE:
        cur.execute(sql, params)
        return cur.fetchone()

    if PDF_BLOB_COLUMN_AVAILABLE is False:
        safe_sql = _replace_pdf_blob_column(sql)
        cur.execute(safe_sql, params)
        return cur.fetchone()

    try:
        cur.execute(sql, params)
        if PDF_BLOB_COLUMN_AVAILABLE is None:
            PDF_BLOB_COLUMN_AVAILABLE = True
        return cur.fetchone()
    except psycopg2.errors.UndefinedColumn:
        cur.connection.rollback()
        PDF_BLOB_COLUMN_AVAILABLE = False
        safe_sql = _replace_pdf_blob_column(sql)
        cur.execute(safe_sql, params)
        return cur.fetchone()


def fetch_template_row(cur, template_identifier, account_id=None, include_field_values=False, allow_refresh=True):
    """
    Retrieve a master template row given either a UUID identifier or a template key (e.g., 'acord24').
    Optionally joins template_data for the provided account to include saved field values.
    """
    if not template_identifier:
        return None

    template_id_str = str(template_identifier).strip()
    normalized_key = template_id_str.lower()
    is_uuid_identifier = False
    try:
        uuid.UUID(template_id_str)
        is_uuid_identifier = True
    except (ValueError, TypeError):
        is_uuid_identifier = False

    if include_field_values and account_id:
        select_clause = '''
            SELECT
                mt.id,
                mt.template_name,
                mt.template_type,
                mt.storage_path,
                mt.file_size,
                mt.pdf_blob,
                mt.form_fields,
                td.field_values
            FROM master_templates mt
            LEFT JOIN template_data td
                ON td.template_id = mt.id AND td.account_id = %s
        '''
        join_params = [account_id]
    else:
        select_clause = '''
            SELECT
                mt.id,
                mt.template_name,
                mt.template_type,
                mt.storage_path,
                mt.file_size,
                mt.pdf_blob,
                mt.form_fields
            FROM master_templates mt
        '''
        join_params = []

    def as_dict(row):
        if row and not isinstance(row, dict):
            return dict(row)
        return row

    row = None
    if is_uuid_identifier:
        row = execute_with_optional_pdf_blob(
            cur,
            select_clause + ' WHERE mt.id = %s',
            join_params + [template_id_str]
        )
        row = as_dict(row)

    if not row and normalized_key:
        row = execute_with_optional_pdf_blob(
            cur,
            select_clause + '''
            WHERE LOWER(mt.template_type) = %s
            ORDER BY mt.updated_at DESC NULLS LAST, mt.created_at DESC
            LIMIT 1
            ''',
            join_params + [normalized_key]
        )
        row = as_dict(row)

    if not row and allow_refresh and normalized_key in MASTER_TEMPLATE_CONFIG:
        config = MASTER_TEMPLATE_CONFIG.get(normalized_key, {})
        try:
            refresh_master_template_from_local(
                normalized_key,
                template_name=config.get('display_name')
            )
            row = execute_with_optional_pdf_blob(
                cur,
                select_clause + '''
                WHERE LOWER(mt.template_type) = %s
                ORDER BY mt.updated_at DESC NULLS LAST, mt.created_at DESC
                LIMIT 1
                ''',
                join_params + [normalized_key]
            )
            row = as_dict(row)
        except Exception as refresh_error:
            print(f"Refresh attempt failed for template '{normalized_key}': {refresh_error}")

    return row


def normalize_incoming_field_values(raw_values):
    """Normalize incoming field values from the client into a flat string dictionary."""
    if not isinstance(raw_values, dict):
        return {}

    normalized = {}

    for key, value in raw_values.items():
        if key is None:
            continue

        key_str = str(key)

        def coerce(val):
            if val is None:
                return ''
            if isinstance(val, bool):
                return 'true' if val else 'false'
            if isinstance(val, (int, float)):
                return str(val)
            if isinstance(val, list):
                return ', '.join(coerce(item) for item in val)
            if isinstance(val, dict):
                if 'value' in val:
                    return coerce(val['value'])
                if 'defaultValue' in val:
                    return coerce(val['defaultValue'])
                if 'displayValue' in val:
                    return coerce(val['displayValue'])
                try:
                    return json.dumps(val)
                except (TypeError, ValueError):
                    return str(val)
            return str(val)

        normalized[key_str] = coerce(value)

    return normalized

@app.route('/api/pdf/template/<template_id>')
@require_sf_session
def serve_pdf_template(template_id):
    """Serve PDF template file for Adobe Embed API"""
    template_id_str = str(template_id or '').strip()
    normalized_template_key = template_id_str.lower()
    conn = None
    cur = None
    template = None
    template_name = None
    template_type = None
    storage_path = ''
    pdf_blob = None
    pdf_content = None
    form_fields_payload = {'fields': []}
    template_id_for_update = template_id_str

    try:
        db_lookup_id = (
            PSYCOPG2_AVAILABLE
            and template_id_str
            and normalized_template_key not in ('null', 'none')
        )

        is_uuid_id = False
        if db_lookup_id:
            try:
                uuid.UUID(template_id_str)
                is_uuid_id = True
            except ValueError:
                is_uuid_id = False

        if db_lookup_id:
            try:
                conn = get_db()
                cur = conn.cursor()
                if is_uuid_id:
                    try:
                        cur.execute(
                            '''
                            SELECT id, template_name, template_type, storage_path, file_size, pdf_blob, form_fields
                            FROM master_templates
                            WHERE id = %s
                            ''',
                            (template_id_str,)
                        )
                    except psycopg2.errors.UndefinedColumn:
                        conn.rollback()
                        cur.execute(
                            '''
                            SELECT id, template_name, template_type, storage_path, file_size, NULL::BYTEA AS pdf_blob, form_fields
                            FROM master_templates
                            WHERE id = %s
                            ''',
                            (template_id_str,)
                        )
                    template = cur.fetchone()

                if (not template) and normalized_template_key:
                    cur.execute(
                        '''
                        SELECT id, template_name, template_type, storage_path, file_size, pdf_blob, form_fields
                        FROM master_templates
                        WHERE LOWER(template_type) = %s
                        ORDER BY updated_at DESC NULLS LAST, created_at DESC
                        LIMIT 1
                        ''',
                        (normalized_template_key,)
                    )
                    template = cur.fetchone()
            except Exception as db_error:
                print(f"Database fetch for template '{template_id_str}' failed: {db_error}")
                template = None

        if template:
            template_id_for_update = template.get('id') or template_id_for_update
            template_name = template.get('template_name')
            template_type = (template.get('template_type') or '').lower()
            storage_path = template.get('storage_path') or ''
            pdf_blob = template.get('pdf_blob')
            form_fields_payload = coerce_form_fields_payload(template.get('form_fields'))
            print(f"Serving PDF template: {template_name} (ID: {template_id_str})")

        if pdf_blob:
            try:
                pdf_content = bytes(pdf_blob)
            except (TypeError, ValueError):
                pdf_content = pdf_blob

        if not pdf_content:
            # Try to resolve from local storage using known template type or ID fallback
            lookup_template_type = template_type or normalized_template_key
            lookup_storage_path = storage_path

            if not lookup_template_type and normalized_template_key in MASTER_TEMPLATE_CONFIG:
                lookup_template_type = normalized_template_key

            if lookup_template_type:
                local_file = resolve_local_template_file(lookup_template_type, lookup_storage_path)
                if local_file:
                    pdf_content = local_file.read_bytes()
                    if not template_name:
                        config = MASTER_TEMPLATE_CONFIG.get(lookup_template_type, {})
                        template_name = config.get('display_name') or lookup_template_type.upper()
                        storage_path = f"local://{local_file.name}"
                        form_fields_payload = form_fields_payload or {'fields': []}
                        template_type = lookup_template_type

        if not pdf_content and template_name:
            pdf_content = create_pdf_with_form_fields(template_name, form_fields_payload)

        if not pdf_content:
            # As a final fallback try using the template_id as a key into the configuration
            config = MASTER_TEMPLATE_CONFIG.get(normalized_template_key)
            if config:
                template_name = config.get('display_name') or normalized_template_key.upper()
                storage_path = f"local://{config.get('filename')}" if config.get('filename') else ''
                local_file = resolve_local_template_file(normalized_template_key, storage_path)
                if local_file:
                    pdf_content = local_file.read_bytes()
                    template_type = normalized_template_key
                    form_fields_payload = {'fields': []}

        if not pdf_content:
            return jsonify({'error': 'Template not available'}), 404

        if not template_name:
            template_name = template_type.upper() if template_type else 'ACORD_TEMPLATE'

        # Attempt to extract and persist form field metadata if missing and DB is available
        if cur and conn and template and not form_fields_payload.get('fields') and pdf_content:
            extracted_fields = extract_form_fields_from_pdf_bytes(pdf_content)
            if extracted_fields:
                try:
                    form_fields_payload = enrich_form_fields_payload({'fields': extracted_fields}, method='pypdf-auto')
                    cur.execute(
                        'UPDATE master_templates SET form_fields = %s, updated_at = NOW() WHERE id = %s',
                        (Json(form_fields_payload), template_id_for_update)
                    )
                    conn.commit()
                    print(f"Extracted and stored {len(extracted_fields)} form fields for template {template_id_str}")
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
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/api/pdf/template/<template_id>/<account_id>')
@require_sf_session
def serve_pdf_template_with_fields(template_id, account_id):
    """Serve PDF template with optional account-specific field values."""
    template_id_str = str(template_id or '').strip()
    normalized_template_key = template_id_str.lower()
    print("=== PDF TEMPLATE REQUESTED ===")
    print(f"Template ID: {template_id_str}")
    print(f"Account ID: {account_id}")

    conn = None
    cur = None
    template_row = None
    template_uuid = None
    template_name = None
    template_type = None
    storage_path = ''
    pdf_blob = None
    pdf_content = None
    form_fields_payload = {'fields': []}
    field_values = {}

    if PSYCOPG2_AVAILABLE:
        try:
            conn = get_db()
            cur = conn.cursor()

            is_uuid_identifier = False
            if template_id_str:
                try:
                    uuid.UUID(template_id_str)
                    is_uuid_identifier = True
                except ValueError:
                    is_uuid_identifier = False

            result = None
            if is_uuid_identifier:
                result = execute_with_optional_pdf_blob(
                    cur,
                    '''
                    SELECT
                        mt.id,
                        mt.template_name,
                        mt.template_type,
                        mt.storage_path,
                        mt.file_size,
                        mt.pdf_blob,
                        mt.form_fields,
                        td.field_values
                    FROM master_templates mt
                    LEFT JOIN template_data td
                        ON td.template_id = mt.id AND td.account_id = %s
                    WHERE mt.id = %s
                    ''',
                    (account_id, template_id_str)
                )

            if not result and normalized_template_key:
                result = execute_with_optional_pdf_blob(
                    cur,
                    '''
                    SELECT
                        mt.id,
                        mt.template_name,
                        mt.template_type,
                        mt.storage_path,
                        mt.file_size,
                        mt.pdf_blob,
                        mt.form_fields,
                        td.field_values
                    FROM master_templates mt
                    LEFT JOIN template_data td
                        ON td.template_id = mt.id AND td.account_id = %s
                    WHERE LOWER(mt.template_type) = %s
                    ORDER BY mt.updated_at DESC NULLS LAST, mt.created_at DESC
                    LIMIT 1
                    ''',
                    (account_id, normalized_template_key)
                )

            if not result and normalized_template_key in MASTER_TEMPLATE_CONFIG:
                try:
                    refresh_master_template_from_local(
                        normalized_template_key,
                        template_name=MASTER_TEMPLATE_CONFIG[normalized_template_key].get('display_name')
                    )
                    result = execute_with_optional_pdf_blob(
                        cur,
                        '''
                        SELECT
                            mt.id,
                            mt.template_name,
                            mt.template_type,
                            mt.storage_path,
                            mt.file_size,
                            mt.pdf_blob,
                            mt.form_fields,
                            td.field_values
                        FROM master_templates mt
                        LEFT JOIN template_data td
                            ON td.template_id = mt.id AND td.account_id = %s
                        WHERE LOWER(mt.template_type) = %s
                        ORDER BY mt.updated_at DESC NULLS LAST, mt.created_at DESC
                        LIMIT 1
                        ''',
                        (account_id, normalized_template_key)
                    )
                except Exception as refresh_error:
                    print(f"Refresh from local failed for '{normalized_template_key}': {refresh_error}")

            if result:
                template_row = result
                template_uuid = template_row.get('id')
                template_name = template_row.get('template_name')
                template_type = (template_row.get('template_type') or '').lower()
                storage_path = template_row.get('storage_path') or ''
                pdf_blob = template_row.get('pdf_blob')
                form_fields_payload = coerce_form_fields_payload(template_row.get('form_fields'))
                raw_field_values = template_row.get('field_values') or {}
                if isinstance(raw_field_values, str):
                    try:
                        field_values = json.loads(raw_field_values)
                    except json.JSONDecodeError:
                        field_values = {}
                else:
                    field_values = raw_field_values or {}
                print(f"Database template located: {template_name} ({template_uuid})")
            else:
                print(f"No database record found for template '{template_id_str}'. Falling back to local storage.")
        except Exception as db_error:
            print(f"Database unavailable for template '{template_id_str}': {db_error}")
            template_row = None
            if conn:
                conn.rollback()

    if not template_name and normalized_template_key in MASTER_TEMPLATE_CONFIG:
        config = MASTER_TEMPLATE_CONFIG[normalized_template_key]
        template_name = config.get('display_name') or normalized_template_key.upper()
        template_type = normalized_template_key
        storage_path = f"local://{config.get('filename')}" if config.get('filename') else ''
        form_fields_payload = {'fields': []}

    if pdf_blob:
        try:
            pdf_content = bytes(pdf_blob)
        except (TypeError, ValueError):
            pdf_content = pdf_blob

    if not pdf_content:
        lookup_type = template_type or normalized_template_key
        local_file = resolve_local_template_file(lookup_type, storage_path)
        if local_file and local_file.exists():
            pdf_content = local_file.read_bytes()
            print(f"Loaded local PDF for template '{lookup_type}' from {local_file}")

    if not pdf_content and template_name:
        pdf_content = create_pdf_with_form_fields(template_name, form_fields_payload)

    if not pdf_content:
        if cur:
            cur.close()
        if conn:
            conn.close()
        return jsonify({'error': 'Template not available'}), 404

    if cur and conn and template_uuid and not field_values:
        try:
            cur.execute(
                '''
                INSERT INTO template_data (account_id, template_id, field_values)
                VALUES (%s, %s, %s)
                ON CONFLICT (account_id, template_id) DO NOTHING
                ''',
                (account_id, template_uuid, json.dumps({}))
            )
            conn.commit()
            print(f"Initialized template_data for account {account_id} / template {template_uuid}")
        except Exception as init_error:
            print(f"Warning: unable to initialize template_data: {init_error}")
            conn.rollback()

    # Merge in Agency Settings from local DB
    effective_template_key = template_type or normalized_template_key
    print(f"=== INJECTION DEBUG ===")
    print(f"Effective template key: {effective_template_key}")
    print(f"Account ID for injection: {account_id}")

    try:
        agency_conn = get_db()
        agency_cur = agency_conn.cursor()

        # First check if table exists
        agency_cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'agency_settings'
            )
        """)
        table_exists = agency_cur.fetchone()
        print(f"Agency settings table exists: {table_exists}")

        if table_exists and table_exists.get('exists', False):
            agency_cur.execute('SELECT * FROM agency_settings WHERE account_id = %s', (account_id,))
            agency_record = agency_cur.fetchone()
            print(f"Agency record found: {agency_record is not None}")

            if agency_record:
                agency_settings = format_agency_settings(agency_record)
                print(f"Agency settings formatted: {list(agency_settings.keys()) if agency_settings else 'None'}")
                print(f"Agency settings values: name={agency_settings.get('name')}, producerName={agency_settings.get('producerName')}, producerPhone={agency_settings.get('producerPhone')}, producerEmail={agency_settings.get('producerEmail')}")
                agency_field_map = resolve_field_mapping(effective_template_key, 'agency')
                print(f"Agency field map: {agency_field_map}")
                if agency_field_map and agency_settings:
                    for source_key, target_field in agency_field_map.items():
                        if target_field and agency_settings.get(source_key):
                            # Only set if not already in field_values
                            if target_field not in field_values or not field_values.get(target_field):
                                field_values[target_field] = agency_settings[source_key]
                                print(f"Injected agency field: {target_field} = {agency_settings[source_key][:30] if len(str(agency_settings[source_key])) > 30 else agency_settings[source_key]}")
                    print(f"Merged Agency Settings into field values")
        else:
            print("Agency settings table does not exist - run schema migration")

        agency_cur.close()
        agency_conn.close()
    except Exception as agency_error:
        print(f"Warning: Could not fetch agency settings: {agency_error}")
        import traceback
        traceback.print_exc()

    # Merge in Named Insured from Supabase
    print(f"=== NAMED INSURED DEBUG ===")
    print(f"Supabase available: {SUPABASE_AVAILABLE}")
    print(f"Supabase client: {supabase is not None}")

    try:
        named_insured_data, ni_error = fetch_named_insured_from_supabase(account_id)
        print(f"Named Insured data: {named_insured_data}")
        print(f"Named Insured error: {ni_error}")

        if named_insured_data:
            named_insured_field_map = get_named_insured_field_map(effective_template_key)
            print(f"Named Insured field map: {named_insured_field_map}")
            named_insured_source = {
                'name': named_insured_data.get('name') or '',
                'address_line1': named_insured_data.get('address_line1') or '',
                'address_line2': named_insured_data.get('address_line2') or '',
                'city': named_insured_data.get('city') or '',
                'state': named_insured_data.get('state') or '',
                'postal_code': named_insured_data.get('postal_code') or '',
                'email': named_insured_data.get('email') or '',
                'phone': named_insured_data.get('phone') or '',
            }
            print(f"Named Insured source values: {named_insured_source}")
            for source_key, target_field in named_insured_field_map.items():
                if target_field and named_insured_source.get(source_key):
                    # Only set if not already in field_values
                    if target_field not in field_values or not field_values.get(target_field):
                        field_values[target_field] = named_insured_source[source_key]
                        print(f"Injected Named Insured field: {target_field} = {named_insured_source[source_key]}")
            print(f"Merged Named Insured from Supabase into field values")
        elif ni_error:
            print(f"Named Insured not available: {ni_error}")
    except Exception as ni_exception:
        print(f"Warning: Could not fetch Named Insured: {ni_exception}")
        import traceback
        traceback.print_exc()

    print(f"=== FINAL FIELD VALUES COUNT: {len(field_values)} ===")

    if field_values:
        print(f"Pre-filling PDF with {len(field_values)} saved field values")
        try:
            if PYMUPDF_AVAILABLE:
                pdf_doc = fitz.open(stream=pdf_content, filetype="pdf")
                filled_count = 0
                checkbox_updates = {}

                for page in pdf_doc:
                    for widget in page.widgets() or []:
                        field_name = widget.field_name
                        if field_name not in field_values:
                            continue

                        saved_value = field_values[field_name]
                        field_type = (widget.field_type_string or '').lower()
                        is_checkbox = field_type in {'checkbox', 'button', 'btn', 'radiobutton'}

                        if not is_checkbox and (saved_value in (None, '', [])):
                            continue

                        try:
                            if field_type == 'text':
                                widget.field_value = str(saved_value)
                                widget.update()
                                filled_count += 1
                            elif field_type in {'checkbox', 'button', 'btn'}:
                                if PYPDF_AVAILABLE:
                                    checkbox_updates[field_name] = saved_value
                                else:
                                    pdf_state, field_state = resolve_checkbox_state(saved_value)
                                    widget.field_value = field_state
                                    widget.update()
                                    filled_count += 1
                            elif field_type == 'radiobutton':
                                widget.field_value = 'X' if str(saved_value).lower() in {'true', '1', 'yes', 'y', 'x'} else 'Off'
                                widget.update()
                                filled_count += 1
                            else:
                                widget.field_value = str(saved_value)
                                widget.update()
                                filled_count += 1
                        except Exception as widget_error:
                            print(f"Failed to fill '{field_name}': {widget_error}")

                filled_pdf_content = pdf_doc.write()
                pdf_doc.close()

                if checkbox_updates and PYPDF_AVAILABLE:
                    filled_pdf_content, successes, failures = fill_checkboxes_with_pypdf(
                        filled_pdf_content,
                        checkbox_updates,
                    )
                    filled_count += len(successes)
                    if failures:
                        print(f"Checkbox updates failed for: {failures}")

                pdf_content = filled_pdf_content
                print(f"PDF prefill complete. Fields filled: {filled_count}")
            else:
                print("PyMuPDF not available; skipping PDF prefill.")
        except Exception as fill_error:
            print(f"Error pre-filling PDF: {fill_error}")

    from flask import Response
    response = Response(
        pdf_content,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'inline; filename="{template_name or "ACORD_TEMPLATE"}.pdf"',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-cache'
        }
    )

    if cur:
        cur.close()
    if conn:
        conn.close()

    return response

@app.route('/api/debug/pymupdf-test/<template_id>/<account_id>')
@require_sf_session
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
@require_sf_session
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
@require_sf_session
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
@require_sf_session
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
        incoming_field_values = normalize_incoming_field_values(field_values)
        field_values = incoming_field_values
        pdf_content = data.get('pdf_content')  # Base64 encoded PDF content
        form_fields_payload = None

        if 'form_fields' in data:
            form_fields_payload = enrich_form_fields_payload(data.get('form_fields'), method='adobe_embed_api')

        if not template_id or not account_id:
            return jsonify({'success': False, 'error': 'Missing template_id or account_id'}), 400

        conn = get_db()
        cur = conn.cursor()

        resolved_template_row = fetch_template_row(
            cur,
            template_id,
            account_id=account_id,
            include_field_values=True
        )

        if not resolved_template_row:
            return jsonify({'success': False, 'error': 'Template not found'}), 404

        resolved_template_id = resolved_template_row.get('id')
        if not resolved_template_id:
            return jsonify({'success': False, 'error': 'Template identifier unavailable'}), 404

        resolved_template_id_str = str(resolved_template_id)
        resolved_template_type = (resolved_template_row.get('template_type') or '').lower()

        if form_fields_payload is None:
            form_fields_payload = coerce_form_fields_payload(resolved_template_row.get('form_fields'))

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
                        final_field_values = {**incoming_field_values, **extracted_fields}
                    else:
                        final_field_values = incoming_field_values
                else:
                    print("pypdf not available, using provided field values")
                    final_field_values = incoming_field_values
                    
            except Exception as extract_error:
                print(f"Error extracting fields from PDF: {extract_error}")
                final_field_values = incoming_field_values
        else:
            final_field_values = incoming_field_values

        # Check if template data already exists for this account
        cur.execute('''
            SELECT id, field_values FROM template_data
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, resolved_template_id_str))

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
        def is_checkbox_checked(value):
            """Determine if a checkbox value represents 'checked'"""
            checked_values = ['/1', '/Yes', '/On', 'Yes', '1', 'On', 'true', 'True', True, 'Y', 'y']
            return str(value).strip() in checked_values if value else False

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
            if is_checkbox_field_name(field_name):
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

        print("Saving field values for template {0} (resolved id: {1}), account {2}: {3} fields (merged from {4} current + {5} existing)".format(
            template_id, resolved_template_id_str, account_id, len(merged_field_values), len(final_field_values), len(existing_field_values)))
        
        if merged_field_values:
            print("Merged field sample:", list(merged_field_values.items())[:5])
            non_empty_saved = {k: v for k, v in merged_field_values.items() if v and str(v).strip()}
            print(f"Non-empty fields being saved: {len(non_empty_saved)}")
            if non_empty_saved:
                print("Non-empty field sample:", list(non_empty_saved.items())[:3])
        else:
            print("WARNING: No field values to save!")

        if existing_data:
            print(f"Updating existing template_data record for account {account_id}, template {resolved_template_id_str}")
            cur.execute('''
                UPDATE template_data
                SET field_values = %s, updated_at = NOW(), version = version + 1
                WHERE account_id = %s AND template_id = %s
            ''', (json.dumps(merged_field_values), account_id, resolved_template_id_str))
            print(f"UPDATE query executed, affected rows: {cur.rowcount}")
        else:
            print(f"Inserting new template_data record for account {account_id}, template {resolved_template_id_str}")
            cur.execute('''
                INSERT INTO template_data (account_id, template_id, field_values)
                VALUES (%s, %s, %s)
            ''', (account_id, resolved_template_id_str, json.dumps(merged_field_values)))
            print(f"INSERT query executed, affected rows: {cur.rowcount}")

        template_fields_updated = False
        if form_fields_payload is not None:
            cur.execute('SELECT form_fields FROM master_templates WHERE id = %s', (resolved_template_id_str,))
            template_row = cur.fetchone()
            existing_fields = coerce_form_fields_payload(template_row.get('form_fields')) if template_row else {'fields': []}
            if existing_fields != form_fields_payload:
                cur.execute(
                    'UPDATE master_templates SET form_fields = %s, updated_at = NOW() WHERE id = %s',
                    (Json(form_fields_payload), resolved_template_id_str)
                )
                template_fields_updated = True

        conn.commit()
        print(f"Database commit successful for account {account_id}, template {resolved_template_id_str}")

        # Verify the data was actually saved by querying it back
        cur.execute('''
            SELECT field_values FROM template_data
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, resolved_template_id_str))
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
            'resolved_template_id': resolved_template_id_str,
            'template_type': resolved_template_type,
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
@require_sf_session
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
@require_sf_session
def get_pdf_fields(template_id, account_id):
    """Get saved PDF field values for a template and account"""
    try:
        conn = get_db()
        cur = conn.cursor()

        template_row = fetch_template_row(
            cur,
            template_id,
            account_id=account_id,
            include_field_values=True
        )

        if not template_row:
            return jsonify({'success': False, 'error': 'Template not found'}), 404

        resolved_template_id = template_row.get('id')
        resolved_template_id_str = str(resolved_template_id) if resolved_template_id else None

        field_values_raw = template_row.get('field_values')
        form_fields_raw = template_row.get('form_fields')

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
            'resolved_template_id': resolved_template_id_str,
            'template_type': (template_row.get('template_type') or '').lower(),
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
    # Run migrations on startup
    ensure_generated_certificates_table()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)



