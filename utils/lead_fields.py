"""
Normalisation and validation for Bot.custom_form_fields.

The lead form the widget renders is always built from two parts:

  1. three hardcoded inputs - name, email, phone - emitted directly by
     renderGatekeeperForm() / renderInChatForm() in static/js/chat.js
  2. every entry in bot.custom_form_fields, appended after them by
     getCustomFieldsHTML()

Nothing used to sit between the admin typing a field name and that name
being appended in step 2. So an admin who added a field called "Phone
number" got a lead form with two phone inputs: the built-in one, plus
their custom one. On submit the lead was written with both `phone` and
`custom_data["Phone number"]`, which can disagree.

There was also no trimming, so "Phone number " was persisted with its
trailing space, and no dedup, so the same name could be added twice -
which additionally collides in the DOM, because getCustomFieldsHTML()
derives element ids by stripping non-alphanumerics from the name.

This module is the single place those rules live. It is authoritative:
static/js/lead_fields.js warns about the same conditions in the browser
for immediate feedback, but reads its list from RESERVED_FIELD_NAMES via
the reserved_lead_field_names template global, so the two cannot drift.
"""

import json

# The three type values the widget knows how to render as an <input type>.
ALLOWED_TYPES = ('text', 'email', 'number')

# Names that collide with an input the widget always renders itself.
# Compared through field_identity(), so case, punctuation and spacing do
# not matter: "Phone-Number", "phone_no " and "PHONE NO" all match.
RESERVED_FIELD_NAMES = frozenset({
    # name
    'name', 'full name', 'fullname', 'your name', 'first name', 'last name',
    'firstname', 'lastname', 'surname',
    # email
    'email', 'e mail', 'email address', 'email id', 'mail', 'mail id',
    # phone
    'phone', 'phone number', 'phone no', 'phoneno', 'phone num',
    'telephone', 'telephone number', 'tel', 'mobile', 'mobile number',
    'mobile no', 'mobile no.', 'cell', 'cell number', 'cellphone',
    'contact', 'contact number', 'contact no', 'whatsapp',
    'whatsapp number', 'whatsapp no',
})


def field_identity(name):
    """
    Collapse a field name to a comparison key.

    Non-alphanumerics become spaces and runs of whitespace collapse, so
    punctuation and spacing variants of the same word map together:

        "Phone-Number"  -> "phone number"
        " phone_no "    -> "phone no"
        "E-Mail"        -> "e mail"
    """
    flattened = ''.join(c if c.isalnum() else ' ' for c in str(name).lower())
    return ' '.join(flattened.split())


def is_reserved(name):
    """True if `name` duplicates a built-in lead field."""
    return field_identity(name) in RESERVED_FIELD_NAMES


def normalize_custom_fields(raw, fallback=None):
    """
    Clean a submitted custom-field list.

    Returns (fields, rejected).

    `fields` is a list of {'name', 'type', 'required'} dicts, safe to
    assign straight to the JSONB column: names trimmed and non-empty,
    type restricted to ALLOWED_TYPES, required coerced to bool.

    `rejected` is a list of (name, reason) pairs for anything dropped
    that the admin deliberately typed, so the caller can tell them.
    Blank rows are dropped silently - clicking "Add Field" and saving
    without typing is not something worth reporting.

    If `raw` cannot be parsed at all, `fallback` is returned unchanged
    rather than clobbering a good config with []. That matters because
    renderCustomFields() rewrites the hidden input from its own state on
    every render: a value we failed to parse but silently replaced with
    [] would wipe the bot's real field list on the next save.
    """
    fallback_fields = list(fallback) if isinstance(fallback, list) else []

    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return [], []
        try:
            raw = json.loads(stripped)
        except (json.JSONDecodeError, TypeError, ValueError):
            return fallback_fields, [
                (None, 'the submitted field list was not valid and has been left unchanged')
            ]

    if not isinstance(raw, list):
        return fallback_fields, []

    fields = []
    rejected = []
    seen = set()

    for entry in raw:
        if not isinstance(entry, dict):
            continue

        name = entry.get('name')
        if not isinstance(name, str):
            continue

        # Trim, and collapse internal whitespace runs so "Order  ID"
        # and "Order ID" cannot both exist.
        name = ' '.join(name.split())
        if not name:
            continue

        key = field_identity(name)

        if key in RESERVED_FIELD_NAMES:
            rejected.append((name, 'already collected as a built-in field'))
            continue

        if key in seen:
            rejected.append((name, 'duplicate of a field above it'))
            continue

        seen.add(key)

        field_type = entry.get('type')
        fields.append({
            'name': name,
            'type': field_type if field_type in ALLOWED_TYPES else 'text',
            'required': bool(entry.get('required')),
        })

    return fields, rejected


def rejection_message(rejected):
    """
    Turn the `rejected` list into one sentence for flash(), or None.

    Named fields are quoted so the admin can find the row they typed.
    """
    if not rejected:
        return None

    parts = []
    for name, reason in rejected:
        parts.append(reason if name is None else '"%s" (%s)' % (name, reason))

    if len(parts) == 1:
        return 'Custom lead field not saved: %s.' % parts[0]
    return 'Custom lead fields not saved: %s.' % '; '.join(parts)
