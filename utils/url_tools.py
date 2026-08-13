"""
URL canonicalization — the SINGLE source of truth for duplicate detection.

This used to live inside routes/admin/scrape_managment.py, where only one
caller could reach it. Every path that accepts or scrapes a URL must use
normalize_url() so that all of these collapse to one key:

    adobe.com
    www.adobe.com
    http://adobe.com
    https://adobe.com
    https://adobe.com/
    https://ADOBE.com
    https:/adobe.com          (single-slash typo)
    https://adobe.com/#pricing

The JS mirror of this lives in templates/partials/_chatbot_scripts.html
(normalizeUrlForDedup). Keep the two in sync — the browser copy is only a
UX nicety; this one is authoritative.
"""

import re
from urllib.parse import urlparse, urlunparse


def normalize_url(raw_url):
    """
    Canonicalize a URL for duplicate detection.

    - fixes the common 'https:/x' single-slash typo
    - forces the https scheme (http/https of the same page are the same page)
    - lowercases the host and strips a leading 'www.'
    - strips the trailing slash and the fragment
    - KEEPS the query string (?page=2 is a different page)

    Returns '' for empty input. Never raises.
    """
    if not raw_url:
        return ''
    u = str(raw_url).strip()
    # 'https:/x' -> 'https://x'
    u = re.sub(r'^(https?):/(?!/)', r'\1://', u, flags=re.IGNORECASE)
    if not u.lower().startswith(('http://', 'https://')):
        u = 'https://' + u
    try:
        parsed = urlparse(u)
        host = (parsed.netloc or '').lower()
        if host.startswith('www.'):
            host = host[4:]
        path = parsed.path.rstrip('/')
        return urlunparse(('https', host, path, '', parsed.query, ''))
    except Exception:
        return u.lower().rstrip('/')


def dedupe_urls(urls):
    """
    Collapse a list of URLs to unique pages, preserving the original order and
    the caller's original URL strings (we scrape what the user gave us, we only
    use the normalized form as the identity key).

    Returns (unique_urls, duplicates_removed_count).
    """
    seen = set()
    unique = []
    removed = 0
    for u in urls or []:
        key = normalize_url(u)
        if not key:
            continue
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        unique.append(u)
    return unique, removed
