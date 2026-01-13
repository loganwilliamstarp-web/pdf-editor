# Next Session Checklist

## Current Status
- Backend save endpoint works (tested via direct API calls).
- Form field metadata now auto-extracts and persists (ACORD 25 has 129 fields stored).
- Popup save flow still posts payloads with `field_count: 0`; Adobe viewer not returning edited values.
- Added extensive logging + `window.PDF_DEBUG` helpers to inspect viewer state.

## Where To Resume
1. **Inspect `PDF_DEBUG` after a save**
   - Open DevTools in the popup *before* editing.
   - Edit a couple of fields, click **Save Fields**.
   - Run `PDF_DEBUG` in the console; capture `context`, `state.viewerReady`, `lastCollected.values`, and whether `apis/getFormFieldValues` exist.
   - If `lastCollected.values` is empty, viewer is not returning edits → plan: poll individual fields via `getFormFields()` or dataLayer.
   - If `lastCollected.values` has data, adjust `savePDFFields` to serialize that structure exactly.

2. **Check Network tab**
   - Confirm `api/pdf/save-fields` request payload matches the edited values.
   - Confirm response has expected `field_count`.

3. **Heroku logs**
   - `heroku logs --tail | grep "Saving field values"` – ensure backend sees non-zero field counts.

4. **Decide remediation**
   - If viewer APIs unreliable, implement direct DOM polling (e.g., iterate `currentPDFViewer.getFormFields()` and read `.value`).

## Reminders
- Tailwind CDN + Adobe GET_FEATURE_FLAG messages are expected noise.
- `index.html` contains all popup logic; latest commit `9e7271c` exposes `PDF_DEBUG` globals.
- Backend logging added in `app.py` (commit `3425603`).

Capture the console/Network/Heroku output first thing tomorrow so we can choose the correct persistence strategy.
