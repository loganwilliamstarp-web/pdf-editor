# Adding New PDF Templates

Use this checklist whenever we add another master template (for example, new ACORD forms). It keeps the filesystem copy, database metadata, and save-callback flow in sync.

## 1. Drop the PDF into the repo
1. Save the finalized PDF into `database/templates/`.
2. Use lowercase snake-case for the filename (e.g., `acord150.pdf`) so helper functions can discover it automatically.

## 2. Register the template in code
1. Update `MASTER_TEMPLATE_CONFIG` near the top of `app.py` with:
   - A unique key (typically the filename without the extension, e.g., `acord150`).
   - `filename`: the exact file name you placed under `database/templates/`.
   - `display_name`: friendly name shown in dashboards.
2. The helper `LOCAL_TEMPLATE_FILES` derives from this config, so no other mapping file needs editing.

## 3. (Optional) Update upload helpers
If we plan to push the PDF into the hosted database via CLI scripts, add the new filename to any helper dictionaries:
- `upload_templates.py`
- `upload_master_templates.py`
- `upload_via_web.py`

This keeps the automation that seeds Heroku/Supabase aware of the template.

## 4. Refresh templates in the running app
With the server running, hit the refresh endpoint so the new metadata (PDF bytes + extracted fields) is persisted:
```
POST /api/templates/refresh
{
  "force": true,
  "templates": ["acord150"]
}
```
If you skip this, the runtime will still fall back to the local PDF (thanks to `execute_with_optional_pdf_blob`), but the database will not record the extracted form fields until someone triggers a refresh.

## 5. Verify end-to-end
1. Call `GET /api/account/<ACCOUNT_ID>/templates` and confirm:
   - The template is listed.
   - `form_fields.extraction.field_count` matches the expected number of fields.
2. Open the template in the Adobe popup and ensure:
   - `/api/pdf/template/<template>/<account>` streams the PDF (watch Heroku logs for “Loaded local PDF …” messages).
   - The first load logs “Extracted and stored X form fields …” if the DB was missing them.
   - Saving via Ctrl+S hits `/api/pdf/save-fields` and responds with `{"success": true, ...}` (Heroku logs will show “Database commit successful …” with no stack traces).

## Notes
- If the production `master_templates` table is missing the `pdf_blob` column, our helper automatically rewrites queries to use a `NULL` placeholder, so you can still add new templates without running a migration first.
- Keep the raw PDFs under version control; this repo acts as the canonical source when reseeding environments.
