"""
Application-wide enums for columns that store a fixed set of values.

These are Python str-enums: each member's .value is the string actually
stored in the database column. SQLAlchemy serialises them transparently
because they inherit from str — no custom TypeDecorator needed.

Usage in models:
    visibility = db.Column(db.String(10), nullable=False, default=Visibility.PUBLIC)

Usage in code:
    if bot.visibility == Visibility.PRIVATE: ...
    bot.visibility = Visibility.PUBLIC       # stores 'public'

The DB columns stay VARCHAR. Enforcement is via CheckConstraint on the
model (validated on INSERT/UPDATE) and Python-side by type. Existing
data is not touched — these strings are what was already being stored.
"""

from enum import Enum


class _StrEnum(str, Enum):
    """str + Enum so members compare equal to their string value."""

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"{self.__class__.__name__}.{self.name}"


# ═══════════════════════════════════════════
# BOT
# ═══════════════════════════════════════════

class Visibility(_StrEnum):
    PUBLIC = 'public'
    PRIVATE = 'private'


class BotType(_StrEnum):
    GENERAL = 'general'
    PLATFORM = 'platform'


class LeadCaptureTiming(_StrEnum):
    DISABLED = 'disabled'
    GATEKEEPER = 'gatekeeper'
    CONV_START = 'conv_start'
    CONV_MIDDLE = 'conv_middle'
    CONV_END = 'conv_end'


# ═══════════════════════════════════════════
# ORGANIZATION
# ═══════════════════════════════════════════

class Plan(_StrEnum):
    FREE = 'free'
    STARTER = 'starter'
    GROWTH = 'growth'
    PRO = 'pro'


class SubscriptionStatus(_StrEnum):
    FREE = 'free'
    ACTIVE = 'active'
    CANCELED = 'canceled'


# ═══════════════════════════════════════════
# SCRAPE JOB
# ═══════════════════════════════════════════

class ScrapeStatus(_StrEnum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'


# ═══════════════════════════════════════════
# CHAT MESSAGE
# ═══════════════════════════════════════════

class MessageRole(_StrEnum):
    USER = 'user'
    BOT = 'bot'


# ═══════════════════════════════════════════
# PAYMENT
# ═══════════════════════════════════════════

class PaymentStatus(_StrEnum):
    COMPLETED = 'completed'
    REFUNDED = 'refunded'
    PARTIALLY_REFUNDED = 'partially_refunded'


# ═══════════════════════════════════════════
# USER
# ═══════════════════════════════════════════

class AuthProvider(_StrEnum):
    EMAIL = 'email'
    GOOGLE = 'google'


class UserRole(_StrEnum):
    MEMBER = 'member'
    ADMIN = 'admin'
    SUPER_ADMIN = 'super_admin'
