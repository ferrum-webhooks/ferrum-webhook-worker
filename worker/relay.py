# file: worker/relay.py
#
# Outbox relay: publishes unpublished outbox rows to the Redis stream.
# Rows are claimed with FOR UPDATE SKIP LOCKED, so any number of worker pods can run a relay.
# Publish-then-mark means a crash in between re-publishes (at-least-once); consumers are idempotent.

import logging
from datetime import datetime, timedelta, timezone

from app import models
from app.metrics import OUTBOX_PUBLISHED
from worker import config

logger = logging.getLogger(__name__)


def relay_once(session_factory, r, batch: int = config.RELAY_BATCH) -> int:
    db = session_factory()
    try:
        rows = (db.query(models.Outbox)
                .filter(models.Outbox.published_at.is_(None))
                .order_by(models.Outbox.id)
                .limit(batch)
                .with_for_update(skip_locked=True)
                .all())
        if not rows:
            return 0
        pipe = r.pipeline(transaction=False)
        for row in rows:
            pipe.xadd(config.STREAM, {"delivery_id": row.delivery_id,
                                      "request_id": row.request_id or "",
                                      "traceparent": row.traceparent or ""})
        pipe.execute()
        now = datetime.now(timezone.utc)
        for row in rows:
            row.published_at = now
        db.commit()
        OUTBOX_PUBLISHED.inc(len(rows))
        return len(rows)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def purge_published(session_factory, retention_seconds: int = config.OUTBOX_RETENTION_SECONDS) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=retention_seconds)
    db = session_factory()
    try:
        n = (db.query(models.Outbox)
             .filter(models.Outbox.published_at.isnot(None), models.Outbox.published_at < cutoff)
             .delete(synchronize_session=False))
        db.commit()
        return n
    finally:
        db.close()
