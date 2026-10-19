import json
import time
from datetime import datetime, timedelta, timezone

import requests

from app import models
from tests.conftest import FakeHTTP
from worker import config, consumer
from worker.delivery import attempt_delivery, backoff_seconds
from worker.relay import relay_once
from worker.scheduler import recover_orphaned, schedule_due_retries
from worker.signing import sign, verify, webhook_headers

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"


# ---------------------------------------------------------------- signing

def test_standard_webhooks_vector():
    # Computed independently with `openssl dgst -sha256 -hmac` over "msg_id.ts.body"
    import base64, hashlib, hmac
    key = base64.b64decode("MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
    expect = base64.b64encode(hmac.new(key, b'msg_p5jXN8AQM9LWM0D4loKWxJek.1614265330.{"test": 2432232314}',
                                       hashlib.sha256).digest()).decode()
    assert sign(SECRET, "msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, b'{"test": 2432232314}') == "v1," + expect


def test_verify_roundtrip_and_tamper():
    body = b'{"a":1}'
    h = webhook_headers(SECRET, "evt_1", body)
    assert verify(SECRET, h, body)
    assert not verify(SECRET, h, b'{"a":2}')                       # body tampered
    assert not verify("whsec_" + "A" * 32, h, body)                # wrong secret
    assert not verify(SECRET, h, body, now=time.time() + 3600)     # outside replay window


# ---------------------------------------------------------------- outbox relay

def test_relay_publishes_once_and_marks_published(sf, r, seed):
    assert relay_once(sf, r) == 1
    assert relay_once(sf, r) == 0
    msgs = r.xrange(config.STREAM)
    assert len(msgs) == 1 and msgs[0][1]["delivery_id"] == str(seed["delivery"])
    db = sf(); assert db.query(models.Outbox).one().published_at is not None; db.close()


def test_relay_crash_between_publish_and_mark_republishes(sf, r, seed):
    """At-least-once: if the mark-published commit is lost, the row is published again
    and the consumer's idempotent claim absorbs the duplicate."""
    relay_once(sf, r)
    db = sf(); db.query(models.Outbox).update({"published_at": None}); db.commit(); db.close()
    relay_once(sf, r)
    assert len(r.xrange(config.STREAM)) == 2

    http = FakeHTTP(200)
    consumer.ensure_group(r)
    msgs = r.xreadgroup(config.GROUP, "c1", {config.STREAM: ">"}, count=10)[0][1]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        consumer.run_batch(sf, r, ex, msgs, http)
    assert len(http.calls) == 1                      # delivered exactly once
    assert r.xpending(config.STREAM, config.GROUP)["pending"] == 0


# ---------------------------------------------------------------- delivery

def test_success_signs_and_sends_stable_id(sf, seed, r):
    http = FakeHTTP(200)
    assert attempt_delivery(sf, seed["delivery"], http=http, redis_client=r) == "success"
    call = http.calls[0]
    h = call["headers"]
    assert h["webhook-id"] == "evt_abc"                       # stable event id
    assert verify(SECRET, h, call["data"])                    # HMAC valid over the exact bytes sent
    assert json.loads(call["data"]) == {"id": "evt_abc", "type": "t", "timestamp": json.loads(call["data"])["timestamp"], "data": {"n": 1}}
    assert call["allow_redirects"] is False
    db = sf()
    d = db.query(models.Delivery).one()
    assert d.status == "success" and d.response_code == 200 and d.retries == 1
    assert db.query(models.Event).one().status == "delivered"
    assert db.query(models.DeliveryAttempt).one().attempt == 1
    db.close()


def test_failure_schedules_retry_without_sleeping(sf, seed, r):
    http = FakeHTTP(500)
    t0 = time.time()
    assert attempt_delivery(sf, seed["delivery"], http=http, redis_client=r) == "retry_scheduled"
    assert time.time() - t0 < 1                                # no time.sleep(delay)
    db = sf()
    d = db.query(models.Delivery).one()
    assert d.status == "retrying" and d.retries == 1 and d.error_message == "HTTP 500"
    nxt = d.next_retry_at if d.next_retry_at.tzinfo else d.next_retry_at.replace(tzinfo=timezone.utc)
    assert 3 < (nxt - datetime.now(timezone.utc)).total_seconds() < 8     # ~5s +/- jitter
    assert db.query(models.Event).one().status == "processing"
    db.close()


def test_timeout_and_dns_errors_are_failures(sf, seed, r):
    http = FakeHTTP(requests.exceptions.ConnectTimeout("slow"))
    assert attempt_delivery(sf, seed["delivery"], http=http, redis_client=r) == "retry_scheduled"
    db = sf(); assert "ConnectTimeout" in db.query(models.Delivery).one().error_message; db.close()


def test_retry_cycle_then_dead_letter(sf, r, seed, monkeypatch):
    monkeypatch.setattr(config, "MAX_ATTEMPTS", 3)
    http = FakeHTTP(503)
    outcomes = []
    for _ in range(3):
        outcomes.append(attempt_delivery(sf, seed["delivery"], http=http, redis_client=r))
        db = sf()   # fast-forward the clock: make the retry due now, then sweep
        db.query(models.Delivery).filter(models.Delivery.status == "retrying").update(
            {"next_retry_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
        db.commit(); db.close()
        schedule_due_retries(sf)
    assert outcomes == ["retry_scheduled", "retry_scheduled", "dead_letter"]
    db = sf()
    d = db.query(models.Delivery).one()
    assert d.status == "dead_letter" and d.moved_to_dlq == 1 and d.retries == 3
    assert db.query(models.Event).one().status == "failed"
    assert db.query(models.DeliveryAttempt).count() == 3
    db.close()
    assert len(r.xrange(config.DLQ_STREAM)) == 1
    # a dead-lettered delivery is never picked up again by stray messages
    assert attempt_delivery(sf, seed["delivery"], http=http, redis_client=r) == "skipped"
    assert len(http.calls) == 3


def test_scheduler_only_moves_due_retries(sf, seed):
    db = sf()
    db.query(models.Delivery).update({"status": "retrying",
                                      "next_retry_at": datetime.now(timezone.utc) + timedelta(minutes=5)})
    db.commit(); db.close()
    assert schedule_due_retries(sf) == 0
    db = sf()
    db.query(models.Delivery).update({"next_retry_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.commit(); db.close()
    assert schedule_due_retries(sf) == 1
    db = sf()
    assert db.query(models.Delivery).one().status == "pending"
    assert db.query(models.Outbox).count() == 2        # original + retry
    db.close()


def test_deleted_webhook_cancels(sf, seed, r):
    db = sf(); db.query(models.Webhook).update({"deleted_at": datetime.now(timezone.utc)})
    db.commit(); db.close()
    http = FakeHTTP(200)
    assert attempt_delivery(sf, seed["delivery"], http=http, redis_client=r) == "cancelled"
    assert http.calls == []


# ---------------------------------------------------------------- crash recovery (XAUTOCLAIM)

def test_crashed_worker_message_is_reclaimed_and_delivered(sf, r, seed, monkeypatch):
    monkeypatch.setattr(config, "RECLAIM_IDLE_MS", 50)
    relay_once(sf, r)
    consumer.ensure_group(r)
    # worker A reads the message, then "crashes": no commit, no XACK
    got = r.xreadgroup(config.GROUP, "worker-A", {config.STREAM: ">"}, count=1)
    assert got and r.xpending(config.STREAM, config.GROUP)["pending"] == 1
    # nothing reclaimable yet...
    assert consumer.reclaim_stale(r, "worker-B") == []
    time.sleep(0.1)
    # ...until it has been idle long enough
    stale = consumer.reclaim_stale(r, "worker-B")
    assert len(stale) == 1

    http = FakeHTTP(200)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        consumer.run_batch(sf, r, ex, stale, http, check_poison=True)
    assert len(http.calls) == 1
    assert r.xpending(config.STREAM, config.GROUP)["pending"] == 0
    db = sf(); assert db.query(models.Delivery).one().status == "success"; db.close()


def test_crash_mid_delivery_stale_lease_is_taken_over(sf, r, seed):
    """Worker died after claiming (status=in_flight). A live lease blocks others; an expired one doesn't."""
    db = sf()
    db.query(models.Delivery).update({"status": "in_flight",
                                      "locked_until": datetime.now(timezone.utc) + timedelta(seconds=30)})
    db.commit(); db.close()
    http = FakeHTTP(200)
    assert attempt_delivery(sf, seed["delivery"], http=http, redis_client=r) == "busy"   # not acked
    db = sf()
    db.query(models.Delivery).update({"locked_until": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.commit(); db.close()
    assert attempt_delivery(sf, seed["delivery"], http=http, redis_client=r) == "success"


def test_orphaned_in_flight_recovered_via_outbox(sf, seed):
    db = sf()
    db.query(models.Delivery).update({"status": "in_flight",
                                      "locked_until": datetime.now(timezone.utc) - timedelta(minutes=10)})
    db.commit(); db.close()
    assert recover_orphaned(sf) == 1
    db = sf(); assert db.query(models.Delivery).one().status == "pending"; db.close()


def test_poison_message_goes_to_dlq(sf, r, monkeypatch):
    monkeypatch.setattr(config, "MAX_MESSAGE_DELIVERIES", 1)
    monkeypatch.setattr(config, "RECLAIM_IDLE_MS", 0)
    consumer.ensure_group(r)
    r.xadd(config.STREAM, {"delivery_id": "999999"})
    for _ in range(2):   # two deliveries => times_delivered 2 > 1
        r.xreadgroup(config.GROUP, "w", {config.STREAM: ">"}, count=1)
        stale = consumer.reclaim_stale(r, "w")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        consumer.run_batch(sf, r, ex, stale, FakeHTTP(200), check_poison=True)
    assert r.xpending(config.STREAM, config.GROUP)["pending"] == 0
    assert r.xrange(config.DLQ_STREAM)[0][1]["reason"] == "poison"


def test_backoff_is_exponential():
    mids = [backoff_seconds(n) for n in (1, 2, 3, 4)]
    for n, v in zip((1, 2, 3, 4), mids):
        assert 5 * 2 ** (n - 1) * 0.79 <= v <= 5 * 2 ** (n - 1) * 1.21


# ---------------------------------------------------------------- SSRF at send time

def test_blocked_target_is_dead_lettered_without_a_request(sf, seed, r, monkeypatch):
    from worker import delivery as dmod
    from app import ssrf
    monkeypatch.setattr(ssrf, "ALLOW_PRIVATE", False)
    db = sf(); db.query(models.Webhook).update({"url": "http://169.254.169.254/latest/meta-data/"})
    db.commit(); db.close()
    http = FakeHTTP(200)
    assert attempt_delivery(sf, seed["delivery"], http=http, redis_client=r) == "dead_letter"
    assert http.calls == []                                  # nothing was sent
    db = sf(); d = db.query(models.Delivery).one()
    assert d.retries == 1 and "blocked target" in d.error_message; db.close()


# ---------------------------------------------------------------- tracing

def test_one_trace_from_ingest_through_retry(sf, r, seed, monkeypatch):
    """traceparent set at ingest travels outbox -> stream -> consumer; both attempts (original and
    scheduled retry) are children of that same trace."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from app.tracing import setup_tracing
    setup_tracing("test")
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))

    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    db = sf(); db.query(models.Outbox).update({"traceparent": tp}); db.query(models.Delivery).update({"traceparent": tp}); db.commit(); db.close()

    http = FakeHTTP(500, 200)
    relay_once(sf, r)
    consumer.ensure_group(r)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        msgs = r.xreadgroup(config.GROUP, "c", {config.STREAM: ">"}, count=5)[0][1]
        assert msgs[0][1]["traceparent"] == tp
        consumer.run_batch(sf, r, ex, msgs, http)
        db = sf()
        db.query(models.Delivery).update({"next_retry_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
        db.commit(); db.close()
        schedule_due_retries(sf); relay_once(sf, r)
        msgs = r.xreadgroup(config.GROUP, "c", {config.STREAM: ">"}, count=5)[0][1]
        assert msgs[0][1]["traceparent"] == tp                 # retry kept the trace
        consumer.run_batch(sf, r, ex, msgs, http)

    spans = exporter.get_finished_spans()
    attempts = [s for s in spans if s.name == "delivery.attempt"]
    assert len(attempts) == 2
    assert {format(s.context.trace_id, "032x") for s in attempts} == {"0af7651916cd43dd8448eb211c80319c"}
    assert all(format(s.parent.span_id, "016x") == "b7ad6b7169203331" for s in attempts)
    posts = [s for s in spans if s.name == "webhook.post"]
    assert [p.attributes.get("http.response.status_code") for p in posts] == [500, 200]
    assert posts[0].status.status_code.name == "ERROR"


def test_pending_delivery_whose_stream_message_was_lost_is_reenqueued(sf, r, seed, monkeypatch):
    """Redis wiped after the relay marked the outbox row published: the delivery would sit `pending`
    forever. The stale-pending sweep re-enqueues it; fresh/backlogged ones are left alone."""
    from worker.scheduler import recover_stale_pending
    relay_once(sf, r)
    r.delete(config.STREAM)                                   # simulate Redis data loss
    assert recover_stale_pending(sf) == 0                     # published just now: could be normal backlog
    db = sf()
    db.query(models.Outbox).update({"published_at": datetime.now(timezone.utc) - timedelta(hours=1)})
    db.commit(); db.close()
    assert recover_stale_pending(sf) == 1
    assert recover_stale_pending(sf) == 0                     # now has an unpublished outbox row waiting
    relay_once(sf, r)
    http = FakeHTTP(200)
    consumer.ensure_group(r)
    msgs = r.xreadgroup(config.GROUP, "c", {config.STREAM: ">"}, count=5)[0][1]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        consumer.run_batch(sf, r, ex, msgs, http)
    db = sf(); assert db.query(models.Delivery).one().status == "success"; db.close()
