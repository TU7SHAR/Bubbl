"""
Bot ID Encoder/Decoder — Obfuscates integer bot IDs for public-facing embed snippets.

Why: Raw sequential integers (data-bot-id="8") expose internal DB structure,
allow enumeration (try 1, 2, 3, ...), and look unprofessional. This encodes
them into short URL-safe strings like "k9Xp3r" that decode back on the server.

Algorithm: XOR with a salt-derived key, then base62 encode.
- Deterministic (same input → same output)
- Reversible (decode_bot_id(encode_bot_id(8)) == 8)
- No DB migration needed (computed on the fly from the integer ID)
- Short output (~6 chars for IDs < 10000)

The SALT is loaded from the BOT_ID_SALT env var (defaults to a built-in value).
Changing the salt invalidates ALL previously issued embed snippets, so don't
change it in production unless you want to force everyone to re-copy their snippet.
"""

import os
import hashlib

_SALT = os.getenv('BOT_ID_SALT', 'bubbl_bot_obfuscate_2026_prod')
_CHARS = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def _get_key(salt=None):
    """Derive a stable XOR key from the salt."""
    s = salt or _SALT
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)


def encode_bot_id(bot_id):
    """Encode an integer bot_id into a short URL-safe string."""
    if bot_id is None:
        return ''
    bot_id = int(bot_id)
    scrambled = bot_id ^ _get_key()
    if scrambled == 0:
        return _CHARS[0]
    result = ''
    n = scrambled
    while n > 0:
        result = _CHARS[n % 62] + result
        n //= 62
    return result


def decode_bot_id(encoded):
    """Decode an encoded bot_id string back to integer. Returns None on failure."""
    if not encoded:
        return None
    try:
        # If it's already a plain integer string, return it directly (backwards compat)
        return int(encoded)
    except (ValueError, TypeError):
        pass
    try:
        n = 0
        for c in encoded:
            idx = _CHARS.index(c)
            n = n * 62 + idx
        return n ^ _get_key()
    except (ValueError, IndexError):
        return None
