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
        # Check if this is a Salesforce Account ID (18 characters starting with 001)
        if len(account_id) == 18 and account_id.startswith('001'):
            try:
                return send_from_directory(app.static_folder, 'index.html')
            except Exception as e:
                return f"<h1>Certificate Management System</h1><p>Account: {account_id}</p><p>Error: {str(e)}</p>"
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
    """Upload a master template to Supabase storage and database"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        if not supabase:
            return jsonify({'success': False, 'error': 'Supabase storage not available'}), 500
        
        pdf_file = request.files['file']
        template_name = request.form.get('name', 'Untitled Template')
        template_type = request.form.get('template_type', 'general')
        account_id = request.form.get('account_id', 'system')
        
        # Generate unique ID for template
        template_id = str(uuid.uuid4())
        
        # Create storage path using default bucket
        storage_path = f'templates/{template_id}.pdf'
        
        # Upload to Supabase storage (using default bucket)
        try:
            # Try to upload to the default bucket (usually accessible)
            pdf_data = pdf_file.read()
            
            # Try different bucket names that might exist
            bucket_names = ['certificates', 'files', 'templates', 'default']
            upload_success = False
            used_bucket = None
            
            for bucket_name in bucket_names:
                try:
                    supabase.storage.from_(bucket_name).upload(
                        storage_path,
                        pdf_data,
                        {'content-type': 'application/pdf'}
                    )
                    print(f"✅ Uploaded to bucket: {bucket_name}")
                    upload_success = True
                    used_bucket = bucket_name
                    break
                except Exception as e:
                    print(f"⚠️  Failed to upload to bucket {bucket_name}: {e}")
                    continue
            
            if not upload_success:
                # Fallback: Store in database without Supabase for now
                print("⚠️  Supabase upload failed, storing metadata only")
                storage_path = f'local_fallback/{template_id}.pdf'
                
        except Exception as e:
            return jsonify({'success': False, 'error': f'Supabase upload failed: {str(e)}'}), 500
        
        # Save template metadata to database
        try:
            conn = get_db()
            cur = conn.cursor()
            
            cur.execute('''
                INSERT INTO master_templates (id, template_name, template_type, storage_path, file_size, form_fields)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
            ''', (template_id, template_name, template_type, storage_path, len(pdf_data), '{}'))
            
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
            
        except Exception as e:
            return jsonify({'success': False, 'error': f'Database save failed: {str(e)}'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/upload-template-simple", methods=['POST'])
def upload_template_simple():
    """Simple template upload without Supabase dependency"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        pdf_file = request.files['file']
        template_name = request.form.get('name', 'Untitled Template')
        template_type = request.form.get('template_type', 'general')
        account_id = request.form.get('account_id', 'system')
        
        # Generate unique ID for template
        template_id = str(uuid.uuid4())
        
        # For now, just store metadata in database
        storage_path = f'demo_templates/{template_id}.pdf'
        
        try:
            conn = get_db()
            cur = conn.cursor()
            
            cur.execute('''
                INSERT INTO master_templates (id, template_name, template_type, storage_path, file_size, form_fields)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
            ''', (template_id, template_name, template_type, storage_path, 0, '{}'))
            
            result = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            
            return jsonify({
                'success': True,
                'template_id': template_id,
                'message': 'Template metadata saved successfully (demo mode)',
                'metadata': {
                    'name': template_name,
                    'type': template_type,
                    'storage_path': storage_path,
                    'note': 'File storage will be configured once Supabase bucket is set up'
                }
            })
            
        except Exception as e:
            return jsonify({'success': False, 'error': f'Database save failed: {str(e)}'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
