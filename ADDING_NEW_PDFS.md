# Adding New PDF Templates

Use this checklist whenever we introduce another master template (for example, ACORD forms). The steps ensure both the filesystem copy and the metadata that powers refresh/fallback logic stay in sync.

## 1. Drop the PDF into the repo
1. Save the finalized PDF into `database/templates/`.
2. Use lowercase snake‑case for the filename (e.g., `acord150.pdf`) so helper functions can discover it automatically.

## 2. Register the template in code
1. Update `MASTER_TEMPLATE_CONFIG` near the top of `app.py` with:
   - A unique key (typically the filename without the extension, e.g., `acord150`).
   - `filename`: the exact file name you placed under `database/templates/`.
   - `display_name`: friendly name shown in dashboards.
2. The helper `LOCAL_TEMPLATE_FILES` derives from this config, so no other mapping file needs editing.

## 3. (Optional) Update upload helpers
If we plan to push the PDF into the hosted database via the CLI scripts, add the new filename to any helper dictionaries:
- `upload_templates.py`
- `upload_master_templates.py`
- `upload_via_web.py`

This keeps the automation that seeds Heroku/Supabase aware of the template.

## 4. Refresh templates in the running app
With the server running, hit the refresh endpoint so the new metadata is persisted:
```
POST /api/templates/refresh
{
  "force": true,
  "templates": ["acord150"]
}
```
If you skip this, the runtime will still fall back to the local PDF (thanks to `execute_with_optional_pdf_blob`), but the database won’t receive the blob until someone triggers a refresh.

## 5. Verify end-to-end
1. Call `GET /api/account/<ACCOUNT_ID>/templates` and confirm the new template is listed.
2. Open the template in the Adobe popup and ensure:
   - `/api/pdf/template/<template>/<account>` streams the PDF (watch Heroku logs for “Loaded local PDF…” messages).
   - Saving via Ctrl+S hits `/api/pdf/save-fields` and persists values.

## Notes
- If the production `master_templates` table is missing the `pdf_blob` column, our helper automatically rewrites queries to use a `NULL` placeholder, so you can still add new templates without running a migration first.
- Keep the raw PDFs under version control; this repo acts as the canonical source when reseeding environments.
