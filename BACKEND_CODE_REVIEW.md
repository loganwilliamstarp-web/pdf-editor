# Backend Code Review - Certificate Management System

## Overview
This document contains the complete backend code for the Certificate Management System, implemented in Flask with PostgreSQL database integration and PDF processing capabilities.

## Key Features
- **PDF Template Management**: Upload, store, and serve PDF templates
- **Field Extraction**: Extract form fields from PDFs using pypdf and PyMuPDF
- **Account-Specific Data**: Store and retrieve field values per account
- **PDF Pre-filling**: Server-side PDF pre-filling using PyMuPDF (fitz)
- **Database Integration**: PostgreSQL with proper schema and migrations
- **Debug Endpoints**: Comprehensive debugging and testing endpoints

## Dependencies
```python
# Core Flask
Flask==3.0.0
Flask-CORS==4.0.0
gunicorn==21.2.0

# PDF Processing
pypdf==3.17.4
PyMuPDF==1.23.14

# Database
psycopg2-binary==2.9.9

# Utilities
python-dotenv==1.0.0
```

## Database Schema

### Tables
1. **master_templates**: Stores PDF templates and metadata
2. **template_data**: Account-specific field values
3. **generated_certificates**: Generated certificate records
4. **certificate_holders**: Certificate holder information

### Key Columns
- `master_templates.pdf_blob`: BYTEA column for storing PDF content
- `template_data.field_values`: JSONB for storing field values
- `template_data.account_id`: Salesforce Account ID (18 chars)

## API Endpoints

### Core Endpoints
- `GET /api/health` - System health check
- `POST /api/setup` - Initialize system and database
- `GET /api/account/<account_id>/templates` - Get available templates
- `POST /api/upload-template` - Upload new template

### PDF Processing
- `GET /api/pdf/template/<template_id>` - Serve PDF template
- `GET /api/pdf/template/<template_id>/<account_id>` - Serve pre-filled PDF
- `POST /api/pdf/save-fields` - Save field values with extraction
- `GET /api/pdf/get-fields/<template_id>/<account_id>` - Get saved field values
- `POST /api/extract-fields` - Extract fields from PDF blob

### Debug Endpoints
- `GET /api/debug/test` - Simple test endpoint
- `GET /api/debug/database` - Database contents inspection
- `GET /api/debug/pymupdf-test/<template_id>/<account_id>` - PyMuPDF testing
- `GET /api/debug/pdf-prefill/<template_id>/<account_id>` - Pre-fill testing
- `POST /api/debug/pdf-content` - PDF content inspection

## Key Functions

### PDF Processing
```python
def extract_form_fields_from_pdf_bytes(pdf_bytes):
    """Extract AcroForm field metadata from PDF bytes using pypdf"""
    
def serve_pdf_template_with_fields(template_id, account_id):
    """Serve PDF with account-specific field values pre-filled using PyMuPDF"""
    
def save_pdf_fields():
    """Save field values with automatic extraction from PDF content"""
```

### Database Operations
```python
def get_db():
    """Get PostgreSQL database connection"""
    
def create_database_schema():
    """Create complete database schema with migrations"""
    
def resolve_local_template_file(template_type, storage_path):
    """Resolve local PDF template file paths"""
```

## Current Issues & Status

### Working Features ✅
- PDF template upload and storage
- Database schema creation and migrations
- Field extraction from PDFs using pypdf
- Account-specific data storage
- Debug endpoints for troubleshooting

### Known Issues ⚠️
1. **PyMuPDF Pre-filling**: The `widgets()` method returns a generator that needs to be converted to a list
2. **Field Value Application**: Server-side pre-filling may not be applying values correctly
3. **Adobe SDK Integration**: Frontend MutationObserver errors (not backend related)

### Recent Fixes 🔧
- Fixed PyMuPDF `widgets()` generator issue by converting to list
- Added comprehensive debugging for field extraction and saving
- Implemented proper JSON parsing for field values from database
- Added database verification and testing endpoints

## Configuration

### Environment Variables
- `DATABASE_URL`: PostgreSQL connection string
- `SUPABASE_URL`: Supabase storage URL (optional)
- `SUPABASE_KEY`: Supabase API key (optional)
- `PORT`: Server port (default: 5000)

### Local Template Files
Templates are stored in `database/templates/` directory with predefined mappings:
- acord25.pdf, acord27.pdf, acord28.pdf, etc.
- Automatic fallback to local files if database storage fails

## Error Handling
- Comprehensive try-catch blocks with detailed logging
- Graceful fallbacks for missing dependencies
- Database rollback on errors
- Detailed error messages in API responses

## Performance Considerations
- PDF content stored as BYTEA in database
- Efficient field extraction using pypdf
- Proper database connection management
- Caching headers for PDF responses

## Security
- CORS enabled for cross-origin requests
- Input validation for all endpoints
- SQL injection prevention using parameterized queries
- File type validation for uploads

## Deployment
- Heroku-ready with Procfile
- Gunicorn WSGI server
- Environment-based configuration
- Database migrations included

## Testing & Debugging
- Multiple debug endpoints for different aspects
- Comprehensive logging throughout
- Database verification after operations
- PDF content inspection capabilities

## Next Steps
1. Fix PyMuPDF pre-filling to ensure values are applied correctly
2. Test field extraction with various PDF types
3. Optimize database queries for better performance
4. Add more comprehensive error handling
5. Implement field validation and constraints

---

*This code review document was generated on 2024-01-01 and reflects the current state of the backend implementation.*
