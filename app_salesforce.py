from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os

app = Flask(__name__, static_folder='frontend/build', static_url_path='')
CORS(app)

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
            # This is a Salesforce Account ID, serve the app with the Account ID
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
                    </div>
                </body>
                </html>
                """
        
        # Try to serve static file
        return send_from_directory(app.static_folder, path)
    except Exception as e:
        return f"File not found: {path}", 404

@app.route("/api/health")
def health():
    return jsonify({
        "status": "healthy", 
        "message": "Certificate Management System is working",
        "timestamp": "2025-01-01T00:00:00.000000"
    })

@app.route("/api/account/<account_id>")
def get_account_info(account_id):
    """Get account information for the given Salesforce Account ID"""
    return jsonify({
        "account_id": account_id,
        "message": "Account data will be integrated with Salesforce",
        "status": "ready"
    })

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
