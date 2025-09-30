from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import io
import uuid
from datetime import datetime

# Optional imports with fallbacks
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
except ImportError:
    print("Warning: psycopg2 not available. Database functionality will be limited.")
    PSYCOPG2_AVAILABLE = False

app = Flask(__name__, static_folder='frontend/build', static_url_path='')
CORS(app)

# Initialize Supabase (for storage only)
if SUPABASE_AVAILABLE:
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_KEY')
    
    if supabase_url and supabase_key:
        supabase: Client = create_client(supabase_url, supabase_key)
    else:
        print("Warning: Supabase credentials not found. Storage functionality will be limited.")
        supabase = None
else:
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
    """Create the storage bucket for certificates"""
    try:
        if not supabase:
            return False
        result = supabase.storage.create_bucket('certificates', public=True)
        return True
    except Exception as e:
        if "already exists" in str(e).lower():
            return True
        return False

def create_database_schema():
    """Create the complete database schema"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Master Templates Table
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
        
        # Template Data by Account
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
        
        # Generated Certificates
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
        
        # Certificate Holders
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
        
        # Create indexes
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_generated_certificates_account ON generated_certificates(account_id);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_certificate_holders_account ON certificate_holders(account_id);')
        
        conn.commit()
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error creating database schema: {e}")
        return False

@app.route("/")
def serve_app():
    try:
        return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        return f"<h1>Certificate Management System</h1><p>Frontend not available: {str(e)}</p>"

@app.route("/<path:path>")
def serve_static(path):
    try:
        # Check if this is a Salesforce Account ID (18 characters starting with 001)
        if len(path) == 18 and path.startswith('001'):
            try:
                return send_from_directory(app.static_folder, 'index.html')
            except Exception as e:
                return f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Certificate Management System</title>
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 40px; }}
                        .header {{ background: #0176d3; color: white; padding: 20px; border-radius: 5px; }}
                        .content {{ margin: 20px 0; }}
                    </style>
                </head>
                <body>
                    <div class="header">
                        <h1>Certificate Management System</h1>
                        <p>Account ID: {path}</p>
                    </div>
                    <div class="content">
                        <h2>Welcome to Certificate Management</h2>
                        <p>This system is integrated with Salesforce Account: <strong>{path}</strong></p>
                        <p>Frontend is loading... Please wait a moment.</p>
                        <hr>
                        <h3>Available Features:</h3>
                        <ul>
                            <li>Upload ACORD PDF Templates</li>
                            <li>Fill PDF Forms with Account Data</li>
                            <li>Generate Certificates</li>
                            <li>Manage Certificate Holders</li>
                        </ul>
                        <p><a href="/api/health">Check API Health</a></p>
                        <p><a href="/api/account/{path}/templates">View Templates</a></p>
                        <p><a href="/api/setup">Initialize Database</a></p>
                    </div>
                </body>
                </html>
                """
        
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
        
        return jsonify({
            'success': True,
            'account_id': account_id,
            'templates': [dict(row) for row in templates]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/account/<account_id>/template/<template_id>/data", methods=['GET'])
def get_template_data(account_id, template_id):
    """Get account-specific data for a template"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT field_values, version, updated_at
            FROM template_data
            WHERE account_id = %s AND template_id = %s
        ''', (account_id, template_id))
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            return jsonify({
                'success': True,
                'account_id': account_id,
                'template_id': template_id,
                'field_values': result['field_values'],
                'version': result['version'],
                'updated_at': result['updated_at'].isoformat()
            })
        else:
            return jsonify({
                'success': True,
                'account_id': account_id,
                'template_id': template_id,
                'field_values': {},
                'version': 0,
                'updated_at': None
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/account/<account_id>/template/<template_id>/data", methods=['POST'])
def save_template_data(account_id, template_id):
    """Save account-specific data for a template"""
    try:
        data = request.get_json()
        field_values = data.get('field_values', {})
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute('''
            INSERT INTO template_data (account_id, template_id, field_values)
            VALUES (%s, %s, %s)
            ON CONFLICT (account_id, template_id) DO UPDATE
            SET field_values = EXCLUDED.field_values,
                updated_at = NOW(),
                version = template_data.version + 1
            RETURNING version
        ''', (account_id, template_id, Json(field_values)))
        
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'account_id': account_id,
            'template_id': template_id,
            'version': result['version']
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
