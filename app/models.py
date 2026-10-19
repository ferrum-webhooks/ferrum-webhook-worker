# file: app/models.py
#
# NOTE: this file is mirrored in ferrum-webhook-worker/app/models.py.
# The gateway owns the schema (alembic); keep both copies identical.

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, JSON, Index, UniqueConstraint,
)
from datetime import datetime, timezone
from app.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)


class Webhook(Base):
    __tablename__ = 'webhooks'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    url = Column(String)
    event_type = Column(String)
    # Standard Webhooks signing secret ("whsec_" + base64). Returned to the owner on create/get.
    secret = Column(String, nullable=True)
    # Soft delete: deliveries keep referencing the row so history survives.
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class Event(Base):
    __tablename__ = 'events'
    __table_args__ = (
        UniqueConstraint('user_id', 'idempotency_key', name='uq_events_user_idempotency'),
    )

    id = Column(Integer, primary_key=True, index=True)
    # Stable external ID ("evt_..."). Sent as `webhook-id` on every delivery attempt.
    public_id = Column(String, unique=True, index=True, nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    payload = Column(JSON)
    status = Column(String, default='pending', index=True)
    event_type = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Delivery(Base):
    """One row per (event, webhook): the delivery's current state.

    status: pending -> in_flight -> success | retrying -> in_flight ... | dead_letter
    Per-attempt history lives in DeliveryAttempt.
    """
    __tablename__ = 'deliveries'
    __table_args__ = (
        UniqueConstraint('event_id', 'webhook_id', name='uq_deliveries_event_webhook'),
        Index('ix_deliveries_due', 'status', 'next_retry_at'),
    )

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey('events.id'), index=True)
    webhook_id = Column(Integer, ForeignKey('webhooks.id'))
    status = Column(String)
    retries = Column(Integer, default=0)
    latency_ms = Column(Integer)
    response_code = Column(Integer)
    attempted_at = Column(DateTime(timezone=True), nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(String, nullable=True)
    moved_to_dlq = Column(Integer, default=0)
    # W3C traceparent of the request that created/replayed this delivery; retries join that trace.
    traceparent = Column(String, nullable=True)


class DeliveryAttempt(Base):
    __tablename__ = 'delivery_attempts'

    id = Column(Integer, primary_key=True, index=True)
    delivery_id = Column(Integer, ForeignKey('deliveries.id'), index=True, nullable=False)
    attempt = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    response_code = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)
    attempted_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Outbox(Base):
    """Transactional outbox: written in the same transaction as the state change,
    published to the Redis stream by the relay, then marked published."""
    __tablename__ = 'outbox'
    __table_args__ = (
        Index('ix_outbox_unpublished', 'published_at', 'id'),
    )

    id = Column(Integer, primary_key=True, index=True)
    delivery_id = Column(Integer, ForeignKey('deliveries.id'), nullable=False)
    request_id = Column(String, nullable=True)
    traceparent = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    published_at = Column(DateTime(timezone=True), nullable=True)
