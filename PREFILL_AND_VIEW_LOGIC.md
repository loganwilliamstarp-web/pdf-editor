# PDF Prefill and View Logic - Core Code

## Overview
This document contains the specific code that handles PDF pre-filling and viewing logic in the Certificate Management System.

## 1. Main PDF Template Serving Function

### `serve_pdf_template_with_fields(template_id, account_id)`
**Location**: Lines 742-980 in `app.py`

This is the core function that serves PDFs with pre-filled field values.

```python
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
                print(f"Field values to fill: {list(field_values.items())[:5] if field_values else 'None'}")
                
                # Load PDF with PyMuPDF
                pdf_doc = fitz.open(stream=pdf_content, filetype="pdf")
                
                filled_count = 0
                failed_fields = []
                
                # Get all form fields
                form_fields = list(pdf_doc[0].widgets())  # Convert generator to list
                print(f"Found {len(form_fields)} form fields in PDF")
                
                # Fill each field from saved values
                for field_name, saved_value in field_values.items():
                    try:
                        if not saved_value or str(saved_value).strip() == '':
                            continue
                            
                        # Find the field by name
                        field_found = False
                        for widget in form_fields:
                            if widget.field_name == field_name:
                                field_found = True
                                field_type = widget.field_type_string
                                
                                print(f"PDF field: '{field_name}' (type: {field_type}) - Saved value: '{saved_value}'")
                                
                                if field_type == 'text':
                                    # Text field
                                    widget.field_value = str(saved_value)
                                    widget.update()
                                    filled_count += 1
                                    print(f"  -> FILLED text field with: '{saved_value}'")
                                elif field_type == 'checkbox':
                                    # Checkbox field
                                    if saved_value in [True, 'true', 'True', '1', 'Yes', 'yes']:
                                        widget.field_value = True
                                        widget.update()
                                        filled_count += 1
                                        print(f"  -> CHECKED checkbox")
                                    else:
                                        widget.field_value = False
                                        widget.update()
                                        print(f"  -> UNCHECKED checkbox")
                                elif field_type == 'radiobutton':
                                    # Radio button field
                                    widget.field_value = str(saved_value)
                                    widget.update()
                                    filled_count += 1
                                    print(f"  -> SELECTED radio option: '{saved_value}'")
                                else:
                                    print(f"  -> SKIPPED (unsupported field type: {field_type})")
                                break
                        
                        if not field_found:
                            print(f"  -> FIELD NOT FOUND: '{field_name}'")
                            failed_fields.append(field_name)
                            
                    except Exception as field_error:
                        print(f"  -> FAILED to fill field '{field_name}': {field_error}")
                        failed_fields.append(field_name)
                        continue
                
                print(f"Successfully filled {filled_count} fields")
                if failed_fields:
                    print(f"Failed to fill {len(failed_fields)} fields: {failed_fields}")
                
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
```

## 2. Field Saving and Extraction Function

### `save_pdf_fields()`
**Location**: Lines 1576-1785 in `app.py`

This function saves field values and extracts them from PDF content.

```python
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
            cur.execute('SELECT form_fields FROM master_templates WHERE id = %s', (template_id))
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
```

## 3. Local Template File Resolution

### `resolve_local_template_file(template_type, storage_path)`
**Location**: Lines 634-662 in `app.py`

This function resolves local PDF template file paths.

```python
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
```

## 4. Key Configuration Constants

```python
# Local template directory and file mappings
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

# PyMuPDF availability check
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("Warning: PyMuPDF not available. PDF pre-filling will be limited.")
```

## 5. Flow Summary

### PDF Viewing Flow:
1. **Request**: `GET /api/pdf/template/<template_id>/<account_id>`
2. **Database Query**: Get template and account-specific field values
3. **PDF Content**: Load from database blob or local file
4. **Field Values**: Parse JSON field values from database
5. **Pre-filling**: Use PyMuPDF to fill PDF fields with saved values
6. **Response**: Return filled PDF or original template

### Field Saving Flow:
1. **Request**: `POST /api/pdf/save-fields` with PDF content
2. **Field Extraction**: Use pypdf to extract field values from PDF
3. **Database Save**: Store extracted values in `template_data` table
4. **Verification**: Query back to confirm data was saved

## 6. Current Issues

### Known Problems:
1. **PyMuPDF Pre-filling**: May not be applying values correctly
2. **Field Extraction**: Sometimes extracts empty values
3. **Database Schema**: `pdf_blob` column may not exist in some deployments

### Debug Points:
- Extensive logging throughout both functions
- Field value verification after database operations
- Multiple extraction methods for robustness
- Graceful fallbacks for missing dependencies

---

*This document contains the core prefill and view logic extracted from the backend code.*
