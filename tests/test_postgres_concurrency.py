"""Concurrency properties that only a real Postgres can prove (SQLite ignores row locks).

Run with:  TEST_DATABASE_URL=postgresql://user:pw@localhost:5432/ferrum_test  python -m pytest tests/test_postgres_concurrency.py
Skipped automatically on SQLite. The database is DROPPED/RECREATED by the fixtures: use a disposable one.
"""
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app import models
from tests.conftest import FakeHTTP
from worker import config
from worker.delivery import attempt_delivery
from worker.relay import relay_once
from worker.scheduler import schedule_due_retries

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                                reason="needs TEST_DATABASE_URL pointing at a real, disposable Postgres")


def _seed_many(sf, n):
    db = sf()
    u = models.User(email="c@example.com", password_hash="x"); db.add(u); db.flush()
    wh = models.Webhook(user_id=u.id, url="https://example.com/h", event_type="t", secret="whsec_" + "A" * 32)
    db.add(wh); db.flush()
    delivery_ids = []
    for i in range(n):
        ev = models.Event(public_id=f"evt_{i}", user_id=u.id, payload={"i": i}, event_type="t")
        db.add(ev); db.flush()
        d = models.Delivery(event_id=ev.id, webhook_id=wh.id, status="pending", retries=0)
        db.add(d); db.flush()
        db.add(models.Outbox(delivery_id=d.id))
        delivery_ids.append(d.id)
    db.commit(); db.close()
    return delivery_ids


def test_concurrent_relays_publish_every_row_exactly_once(sf, r):
    """FOR UPDATE SKIP LOCKED: N relays draining one outbox never publish the same row twice nor skip one."""
    ids = _seed_many(sf, 600)
    stop = threading.Event()
    errors = []

    def relay():
        try:
            while not stop.is_set():
                if relay_once(sf, r, batch=25) == 0:
                    return
        except Exception as e:      # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=relay) for _ in range(6)]
    [t.start() for t in threads]; [t.join(60) for t in threads]
    assert not errors, errors
    published = Counter(int(m[1]["delivery_id"]) for m in r.xrange(config.STREAM))
    assert set(published) == set(ids)
    assert max(published.values()) == 1, "a row was published twice"
    db = sf(); assert db.query(models.Outbox).filter(models.Outbox.published_at.is_(None)).count() == 0; db.close()


def test_only_one_of_many_concurrent_workers_delivers(sf, r):
    """The atomic pending -> in_flight claim: 12 workers race on one delivery; the HTTP request is sent once."""
    ids = _seed_many(sf, 1)
    http = FakeHTTP(200)
    slow_post = http.post

    def post(*a, **kw):
        time.sleep(0.2)             # hold the lease long enough for every other worker to collide with it
        return slow_post(*a, **kw)
    http.post = post

    with ThreadPoolExecutor(12) as ex:
        outcomes = list(ex.map(lambda _: attempt_delivery(sf, ids[0], http=http, redis_client=r), range(12)))
    assert Counter(outcomes)["success"] == 1
    assert set(outcomes) <= {"success", "busy", "skipped"}
    assert len(http.calls) == 1


def test_concurrent_schedulers_requeue_each_due_retry_once(sf):
    ids = _seed_many(sf, 200)
    db = sf()
    db.query(models.Outbox).delete()
    db.query(models.Delivery).update({"status": "retrying",
                                      "next_retry_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.commit(); db.close()
    with ThreadPoolExecutor(6) as ex:
        counts = list(ex.map(lambda _: schedule_due_retries(sf, limit=20), range(30)))
    assert sum(counts) == 200
    db = sf()
    per_delivery = Counter(o.delivery_id for o in db.query(models.Outbox).all())
    assert set(per_delivery) == set(ids) and max(per_delivery.values()) == 1
    db.close()
