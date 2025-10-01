# Checkbox Pre-filling Code - Complete Logic

## 1. Checkbox Detection and Debugging

```python
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
```

## 2. Checkbox Field Collection

```python
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
```

## 3. Main Pre-filling Loop

```python
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
```

## 4. Database Field Values Retrieval

```python
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
```

## 5. Current Issues Identified

### Issue 1: `widget.update()` is commented out
- **Problem**: Checkboxes won't render without `widget.update()`
- **Location**: Lines 991, 1034
- **Fix**: Uncomment `widget.update()` calls

### Issue 2: Field type detection
- **Problem**: Checkboxes might be detected as `Button` or `RadioButton` instead of `CheckBox`
- **Location**: Line 956 `field_type = widget.field_type_string`
- **Fix**: Check debug output to see actual field types

### Issue 3: Field value matching
- **Problem**: Field names in database might not match PDF field names
- **Location**: Line 948 `if field_name in field_values`
- **Fix**: Check if field names match between database and PDF

## 6. Debugging Steps

1. **Check field types**: Look at debug output to see if checkboxes are `CheckBox`, `Button`, or `RadioButton`
2. **Check field names**: Verify database field names match PDF field names
3. **Check saved values**: Confirm database has checkbox values like `/Yes`, `/Off`, `/1`
4. **Enable updates**: Uncomment `widget.update()` calls to ensure rendering
5. **Check widget properties**: Look at `field_states`, `button_states` in debug output

## 7. Quick Fix

The most likely issue is that `widget.update()` is commented out. Try uncommenting it:

```python
# Change this:
# widget.update()  # Commented out to preserve styling

# To this:
widget.update()  # Required for rendering
```

This should make checkboxes pre-fill properly.
