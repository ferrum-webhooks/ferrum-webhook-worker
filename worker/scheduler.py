# file: worker/scheduler.py
#
# Scheduled retries. A failed delivery is parked as status='retrying' with next_retry_at in the
# future -- no worker sleeps. This sweep moves due deliveries back to 'pending' and writes an
# outbox row in the same transaction, so the relay re-enqueues them. Durable (it is all in
# Postgres) and safe with many pods (SKIP LOCKED).

import logging
from datetime import datetime, timedelta, timezone

from app import models
from worker import config

logger = logging.getLogger(__name__)


def schedule_due_retries(session_factory, limit: int = 500) -> int:
    db = session_factory()
    try:
        now = datetime.now(timezone.utc)
        due = (db.query(models.Delivery)
               .filter(models.Delivery.status == "retrying",
                       models.Delivery.next_retry_at <= now)
               .order_by(models.Delivery.next_retry_at)
               .limit(limit)
               .with_for_update(skip_locked=True)
               .all())
        for d in due:
            d.status = "pending"
            d.next_retry_at = None
            db.add(models.Outbox(delivery_id=d.id, traceparent=d.traceparent))
        db.commit()
        return len(due)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def recover_orphaned(session_factory, limit: int = 500) -> int:
    """Safety net for the stream path: a delivery stuck `in_flight` past its lease whose stream
    message was lost (e.g. Redis data loss) is put back on the outbox."""
    db = session_factory()
    try:
        now = datetime.now(timezone.utc)
        stuck = (db.query(models.Delivery)
                 .filter(models.Delivery.status == "in_flight",
                         models.Delivery.locked_until < now - timedelta(seconds=config.LEASE_SECONDS))
                 .limit(limit)
                 .with_for_update(skip_locked=True)
                 .all())
        for d in stuck:
            d.status = "pending"
            d.locked_until = None
            db.add(models.Outbox(delivery_id=d.id, traceparent=d.traceparent))
        db.commit()
        return len(stuck)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def recover_stale_pending(session_factory, limit: int = 500) -> int:
    """Durability net for the Redis side: `pending` deliveries whose every outbox row was published more
    than STALE_PENDING_SECONDS ago (and none is waiting) have lost their stream message. Re-enqueue them.
    Duplicates are harmless: the atomic claim makes the second message a no-op."""
    db = session_factory()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=config.STALE_PENDING_SECONDS)
        fresh_or_waiting = (db.query(models.Outbox.id)
                            .filter(models.Outbox.delivery_id == models.Delivery.id,
                                    (models.Outbox.published_at.is_(None)) |
                                    (models.Outbox.published_at > cutoff))
                            .exists())
        stale = (db.query(models.Delivery)
                 .filter(models.Delivery.status == "pending", ~fresh_or_waiting)
                 .limit(limit)
                 .with_for_update(skip_locked=True)
                 .all())
        for d in stale:
            db.add(models.Outbox(delivery_id=d.id, traceparent=d.traceparent))
        db.commit()
        return len(stale)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
