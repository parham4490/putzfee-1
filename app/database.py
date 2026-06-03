"""Database schema and async connection helpers.

The project uses the lightweight `databases` library on top of `asyncpg`
for runtime queries, and SQLAlchemy *Core* metadata for migrations
(via Alembic). No ORM is used — queries are explicit and asynchronous.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import sqlalchemy as sa
from databases import Database
from sqlalchemy.dialects import postgresql as pg

try:
    from .config import get_settings
except ImportError:
    from config import get_settings

_settings = get_settings()

# Strip the +asyncpg suffix for SQLAlchemy synchronous tooling (Alembic).
SYNC_DATABASE_URL = _settings.DATABASE_URL.replace(
    "postgresql+asyncpg://", "postgresql://"
)
ASYNC_DATABASE_URL = _settings.DATABASE_URL

database = Database(ASYNC_DATABASE_URL)
metadata = sa.MetaData()


# ---------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------
ORDER_STATUSES = (
    "PENDING_REVIEW",          # admin has not seen yet
    "AWAITING_USER_CONFIRM",   # admin proposed times, user must pick one
    "TIME_CONFIRMED",          # user picked, awaiting price
    "PRICE_CONFIRMED",         # admin set price + exec duration, awaiting start
    "IN_PROGRESS",             # work started
    "COMPLETED",               # finished
    "CANCELLED",               # user or admin cancelled
)

SLOT_STATUSES = (
    "PROPOSED",
    "CONFIRMED",
    "REJECTED",
    "EXPIRED",
)

PAYMENT_TYPES = ("cash",)  # only cash for now; reserved for future

DEVICE_PLATFORMS = ("android", "ios", "web")


# ---------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------
users = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("phone", sa.String(32), nullable=False, unique=True, index=True),
    sa.Column("full_name", sa.String(120), nullable=False),
    sa.Column("password_hash", sa.String(255), nullable=False),
    sa.Column("address", sa.String(500), nullable=True),
    sa.Column("photo_url", sa.String(500), nullable=True),
    sa.Column("locale", sa.String(8), nullable=False, server_default="en"),
    sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.text("false")),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

cars = sa.Table(
    "cars",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("brand", sa.String(80), nullable=False),
    sa.Column("model", sa.String(80), nullable=False),
    sa.Column("plate", sa.String(40), nullable=True),
    sa.Column("color", sa.String(40), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

services = sa.Table(
    "services",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("key", sa.String(64), nullable=False, unique=True),
    sa.Column("name_i18n", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "description_i18n", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    ),
    sa.Column("icon", sa.String(120), nullable=True),
    sa.Column("base_price", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
    sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("requires_car", sa.Boolean, nullable=False, server_default=sa.text("false")),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

promotions = sa.Table(
    "promotions",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("key", sa.String(64), nullable=False, unique=True),
    sa.Column("title_i18n", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "description_i18n", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    ),
    sa.Column("image_url", sa.String(500), nullable=True),
    sa.Column("discount_percent", sa.Numeric(5, 2), nullable=True),
    sa.Column("flat_discount", sa.Numeric(12, 2), nullable=True),
    sa.Column("min_services", sa.Integer, nullable=True),
    sa.Column("applies_to_keys", pg.JSONB, nullable=True),
    sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

requests = sa.Table(
    "requests",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "status",
        sa.String(32),
        nullable=False,
        server_default=sa.text("'PENDING_REVIEW'"),
    ),
    sa.Column("service_keys", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column(
        "car_id",
        sa.BigInteger,
        sa.ForeignKey("cars.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("car_services", pg.JSONB, nullable=True),
    sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
    sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
    sa.Column("address_text", sa.String(500), nullable=True),
    sa.Column("house_number", sa.String(40), nullable=True),
    sa.Column("visit1_datetime", sa.DateTime(timezone=False), nullable=True),
    sa.Column("visit2_datetime", sa.DateTime(timezone=False), nullable=True),
    sa.Column("notes", sa.Text, nullable=True),
    sa.Column("total_price", sa.Numeric(12, 2), nullable=True),
    sa.Column("exec_duration_minutes", sa.Integer, nullable=True),
    sa.Column(
        "payment_type",
        sa.String(16),
        nullable=False,
        server_default=sa.text("'cash'"),
    ),
    sa.Column("promotion_id", sa.BigInteger, sa.ForeignKey("promotions.id"), nullable=True),
    sa.Column("cancel_reason", sa.String(500), nullable=True),
    sa.Column("started_at", sa.DateTime(timezone=False), nullable=True),
    sa.Column("finished_at", sa.DateTime(timezone=False), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=False),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=False),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

schedule_slots = sa.Table(
    "schedule_slots",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "request_id",
        sa.BigInteger,
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("start_at", sa.DateTime(timezone=False), nullable=False, index=True),
    sa.Column("end_at", sa.DateTime(timezone=False), nullable=False),
    sa.Column(
        "status",
        sa.String(16),
        nullable=False,
        server_default=sa.text("'PROPOSED'"),
    ),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=False),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

# Confirmed bookings. Only one row per request. The UNIQUE INDEX on
# start_at prevents two confirmed bookings from sharing the same start
# (slots are fixed-length, so equal start = collision).
appointments = sa.Table(
    "appointments",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "request_id",
        sa.BigInteger,
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("start_at", sa.DateTime(timezone=False), nullable=False, unique=True),
    sa.Column("end_at", sa.DateTime(timezone=False), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=False),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

reviews = sa.Table(
    "reviews",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "request_id",
        sa.BigInteger,
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("rating", sa.SmallInteger, nullable=False),
    sa.Column("comment", sa.Text, nullable=True),
    sa.Column("is_public", sa.Boolean, nullable=False, server_default=sa.text("true")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.CheckConstraint("rating BETWEEN 1 AND 5", name="reviews_rating_range"),
)

notifications = sa.Table(
    "notifications",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("body", sa.String(1000), nullable=True),
    sa.Column("payload", pg.JSONB, nullable=True),
    sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

device_tokens = sa.Table(
    "device_tokens",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("token", sa.String(500), nullable=False, unique=True),
    sa.Column(
        "platform", sa.String(16), nullable=False, server_default=sa.text("'android'")
    ),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Column(
        "last_used_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

login_attempts = sa.Table(
    "login_attempts",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("phone", sa.String(32), nullable=False, index=True),
    sa.Column("ip", sa.String(64), nullable=True, index=True),
    sa.Column("success", sa.Boolean, nullable=False),
    sa.Column(
        "attempted_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        index=True,
    ),
)

refresh_tokens = sa.Table(
    "refresh_tokens",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Column(
        "last_used_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

password_resets = sa.Table(
    "password_resets",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
)

ai_usage = sa.Table(
    "ai_usage",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("completion_tokens", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        index=True,
    ),
)


# ---------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------
@asynccontextmanager
async def lifespan_connect():
    """Connect and disconnect the global Database instance."""
    await database.connect()
    try:
        yield
    finally:
        await database.disconnect()


async def acquire_request_lock(request_id: int) -> None:
    """Take a Postgres advisory lock for the given request.

    The lock is released automatically at the end of the transaction.
    Use inside ``async with database.transaction():`` blocks.
    """
    await database.execute(
        "SELECT pg_advisory_xact_lock(:req)", values={"req": int(request_id)}
    )


async def acquire_slot_lock(slot_epoch: int) -> None:
    """Take an advisory lock keyed by slot start (epoch seconds).

    Use this when checking + creating an appointment so that two
    concurrent confirmations of the same slot serialize on the lock.
    """
    await database.execute(
        "SELECT pg_advisory_xact_lock(:k)", values={"k": int(slot_epoch)}
    )
