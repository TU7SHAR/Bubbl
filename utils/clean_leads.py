"""
clean_leads.py — One-time migration to sanitize existing lead custom_data.

Run once from your project root:
    python clean_leads.py

It re-uses the same sanitize_custom_data logic as api.py, so behaviour is
identical to what new leads will get going forward.
"""

import json
import re
from app import app          # adjust import if your Flask app factory is named differently
from models.models import db, Lead, Bot


# ── same coerce_number + sanitize_custom_data as api.py ─────────────────────

def coerce_number(val):
    if val is None:
        return "0"
    s = str(val).strip().lower()
    multipliers = [
        (r'(\d+(?:\.\d+)?)\s*cr(?:ore)?',           1_00_00_000),
        (r'(\d+(?:\.\d+)?)\s*billion',               1_000_000_000),
        (r'(\d+(?:\.\d+)?)\s*million',               1_000_000),
        (r'(\d+(?:\.\d+)?)\s*(?:lakh|lac(?:s|h)?)',  1_00_000),
        (r'(\d+(?:\.\d+)?)\s*thousand',              1_000),
        (r'(\d+(?:\.\d+)?)\s*k\b',                   1_000),
        (r'(\d+(?:\.\d+)?)\s*l\b',                   1_00_000),
    ]
    for pattern, mult in multipliers:
        m = re.search(pattern, s)
        if m:
            return str(int(float(m.group(1)) * mult))
    s = re.sub(r'[^\d.\-]', '', s)
    if '-' in s:
        s = s.split('-')[0]
    try:
        return str(int(float(s))) if s else "0"
    except ValueError:
        return "0"


def sanitize_custom_data(raw_dict, field_schema_json=""):
    if not raw_dict or not isinstance(raw_dict, dict):
        return {}

    field_types = {}
    if field_schema_json:
        try:
            for f in json.loads(field_schema_json):
                name = f.get('name', '')
                if name:
                    field_types[name.lower()] = f.get('type', 'text')
        except Exception:
            pass

    cleaned = {}
    for key, value in raw_dict.items():
        if key == 'Priority':
            cleaned['Priority'] = value
            continue
        if value is None or str(value).strip().lower() in (
            '', 'none', 'null', 'n/a', 'not provided', '-'
        ):
            continue
        clean_key = key.strip().title()
        if field_types.get(key.lower()) == 'number':
            cleaned[clean_key] = coerce_number(value)
        else:
            cleaned[clean_key] = str(value).strip()
    return cleaned


# ── migration runner ─────────────────────────────────────────────────────────

def run():
    with app.app_context():
        leads = Lead.query.all()
        updated = 0
        skipped = 0

        for lead in leads:
            if not lead.custom_data:
                skipped += 1
                continue

            # Get the field schema for this lead's bot (for number-type detection)
            schema_json = ""
            if lead.bot_ref:
                schema_json = getattr(lead.bot_ref, 'custom_form_fields', '') or ""

            old = dict(lead.custom_data)
            new = sanitize_custom_data(old, schema_json)

            if new != old:
                lead.custom_data = new
                updated += 1
                print(f"  Lead #{lead.id} ({lead.email})")
                print(f"    BEFORE: {old}")
                print(f"    AFTER:  {new}")

        db.session.commit()
        print(f"\nDone. {updated} leads updated, {skipped} skipped (no custom_data).")


if __name__ == "__main__":
    run()