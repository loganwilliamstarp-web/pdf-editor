"""
Extract fillable form field metadata from PDF templates stored in Postgres.

The script reads PDF blobs from the `master_templates` table, extracts
AcroForm field definitions, and stores them in the `form_fields` JSONB column.

Usage examples:
    python extract_template_fields.py
    python extract_template_fields.py --template-id 123e4567-e89b-12d3-a456-426614174000
    python extract_template_fields.py --dry-run

The script expects the DATABASE_URL environment variable to be set to a
Postgres connection string.
"""

import argparse
import datetime as dt
import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor

try:
    from pypdf import PdfReader
except ImportError as exc:  # pragma: no cover - pypdf should be installed per requirements
    raise SystemExit(
        "pypdf is required for field extraction. Install dependencies first."
    ) from exc


LOCAL_TEMPLATE_DIR = Path('database/templates')
LOGGER = logging.getLogger("pdf_field_extractor")


def configure_logging(verbose: bool = False) -> None:
    """Configure root logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format='%(levelname)s %(message)s')


def get_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL environment variable is not set')
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor, sslmode='require')


def row_pdf_bytes(row: Dict[str, Any]) -> Optional[bytes]:
    """Return PDF bytes from a database row, loading from disk if needed."""
    blob = row.get('pdf_blob')
    if blob is not None:
        if isinstance(blob, memoryview):
            return blob.tobytes()
        if isinstance(blob, (bytes, bytearray)):
            return bytes(blob)
        try:
            return bytes(blob)
        except (TypeError, ValueError):
            LOGGER.debug('Unable to coerce pdf_blob for template %s', row.get('id'))

    storage_path = (row.get('storage_path') or '').strip()
    template_type = (row.get('template_type') or '').strip().lower()

    candidates: List[Path] = []
    if storage_path:
        storage_candidate = LOCAL_TEMPLATE_DIR / Path(storage_path).name
        candidates.append(storage_candidate)
    if template_type:
        candidates.append(LOCAL_TEMPLATE_DIR / f'{template_type}.pdf')
    template_name = (row.get('template_name') or '').strip()
    if template_name:
        normalized = template_name.lower().replace(' ', '_')
        candidates.append(LOCAL_TEMPLATE_DIR / f'{normalized}.pdf')

    for candidate in candidates:
        if candidate.exists():
            return candidate.read_bytes()

    return None


def extract_form_fields(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """Extract AcroForm field metadata from a PDF."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    field_map = reader.get_fields() or {}
    fields: List[Dict[str, Any]] = []

    for name, data in field_map.items():
        if not name:
            continue

        field_type = str(data.get('/FT', '')).strip('/') or 'text'
        flags = int(data.get('/Ff', 0))
        options: List[str] = []
        if '/Opt' in data:
            opt_values = data.get('/Opt') or []
            if isinstance(opt_values, (list, tuple)):
                for entry in opt_values:
                    options.append(str(entry))
            else:
                options.append(str(opt_values))

        default_value: Optional[str]
        if '/V' in data and data.get('/V') is not None:
            default_value = str(data.get('/V'))
        else:
            default_value = None

        field_entry = {
            'name': str(name),
            'type': field_type,
            'label': str(data.get('/TU') or data.get('/T') or name),
            'required': bool(flags & 2),
            'default_value': default_value,
            'flags': flags,
            'options': options,
        }

        rect = data.get('/Rect')
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            try:
                field_entry['rect'] = [float(coord) for coord in rect]
            except (TypeError, ValueError):
                pass

        try:
            field_entry['page'] = int(getattr(data.get('/P'), 'idnum', None)) if data.get('/P') else None
        except (TypeError, ValueError):
            field_entry['page'] = None

        fields.append(field_entry)

    return fields


def parse_existing_form_fields(raw_value: Any) -> Optional[Dict[str, Any]]:
    if raw_value in (None, ''):
        return None
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return None
    return None


def normalize_form_fields_payload(fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        'fields': fields,
        'extraction': {
            'method': 'pypdf',
            'extracted_at': dt.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
            'field_count': len(fields),
        },
    }


def should_update(existing: Optional[Dict[str, Any]], new_payload: Dict[str, Any]) -> bool:
    if not existing:
        return True
    try:
        return json.dumps(existing, sort_keys=True) != json.dumps(new_payload, sort_keys=True)
    except TypeError:
        return True


def process_templates(template_ids: Optional[Iterable[str]] = None, dry_run: bool = False) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if template_ids:
                ids = list(template_ids)
                placeholders = ','.join(['%s'] * len(ids))
                query = (
                    f"SELECT id, template_name, template_type, storage_path, pdf_blob, form_fields "
                    f"FROM master_templates WHERE id IN ({placeholders}) ORDER BY template_name"
                )
                cur.execute(query, ids)
            else:
                cur.execute(
                    'SELECT id, template_name, template_type, storage_path, pdf_blob, form_fields '
                    'FROM master_templates ORDER BY template_name'
                )
            rows = cur.fetchall()

        total = len(rows)
        updated = 0
        skipped = 0
        missing_pdf = 0

        for row in rows:
            template_id = row['id']
            template_name = row.get('template_name') or template_id
            pdf_bytes = row_pdf_bytes(row)
            if not pdf_bytes:
                LOGGER.warning('No PDF content available for template %s (%s)', template_name, template_id)
                missing_pdf += 1
                continue

            fields = extract_form_fields(pdf_bytes)
            payload = normalize_form_fields_payload(fields)
            existing_payload = parse_existing_form_fields(row.get('form_fields'))

            if not should_update(existing_payload, payload):
                LOGGER.debug('Template %s already has up-to-date form field data', template_name)
                skipped += 1
                continue

            LOGGER.info('Updating form field metadata for %s (%s) [%d fields]', template_name, template_id, len(fields))
            if dry_run:
                updated += 1
                continue

            with conn.cursor() as cur_update:
                cur_update.execute(
                    'UPDATE master_templates SET form_fields = %s, updated_at = NOW() WHERE id = %s',
                    (Json(payload), template_id),
                )
            conn.commit()
            updated += 1

        LOGGER.info('Processed %d templates: %d updated, %d skipped, %d missing PDF', total, updated, skipped, missing_pdf)


def main() -> None:
    parser = argparse.ArgumentParser(description='Extract form fields from PDF templates stored in Postgres.')
    parser.add_argument('--template-id', action='append', dest='template_ids', help='Limit extraction to specific template id(s). Can be used multiple times.')
    parser.add_argument('--dry-run', action='store_true', help='Run extraction without writing to the database.')
    parser.add_argument('--verbose', action='store_true', help='Enable debug logging output.')
    args = parser.parse_args()

    configure_logging(verbose=args.verbose)

    template_ids = args.template_ids
    if template_ids:
        LOGGER.info('Restricting extraction to %d template(s).', len(template_ids))

    try:
        process_templates(template_ids=template_ids, dry_run=args.dry_run)
    except Exception as exc:
        LOGGER.error('Extraction failed: %s', exc)
        raise


if __name__ == '__main__':
    main()
