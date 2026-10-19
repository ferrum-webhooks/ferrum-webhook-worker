# file: worker/delivery.py
#
# One delivery attempt. Idempotent: a duplicate/stale stream message finds the delivery no
# longer `pending` and does nothing.

import json
import logging
import random
import time
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from opentelemetry import trace

from app import models
from app.ssrf import BlockedTarget, check_url
from app.tracing import context_from_traceparent, tracer
from app.metrics import (
    DELIVERY_FAILURE, DELIVERY_LATENCY, DELIVERY_SUCCESS, DLQ_EVENTS, DUPLICATES_SKIPPED,
    END_TO_END_LATENCY, QUEUE_DELAY, RETRY_ATTEMPTS,
)
from worker import config
from worker.signing import webhook_headers

logger = logging.getLogger(__name__)

TERMINAL = ("success", "dead_letter", "cancelled")


def backoff_seconds(attempt: int) -> float:
    """Delay after the `attempt`-th failure (1-based): exponential with jitter."""
    base = min(config.RETRY_BASE_SECONDS * (2 ** (attempt - 1)), config.RETRY_MAX_SECONDS)
    return base * (1 + random.uniform(-config.RETRY_JITTER, config.RETRY_JITTER))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _claim(db, delivery_id: int, now: datetime) -> bool:
    """Atomically move pending (or orphaned in_flight) -> in_flight. False = not ours / done."""
    n = (db.query(models.Delivery)
         .filter(models.Delivery.id == delivery_id,
                 (models.Delivery.status == "pending") |
                 ((models.Delivery.status == "in_flight") & (models.Delivery.locked_until < now)))
         .update({"status": "in_flight",
                  "locked_until": now + timedelta(seconds=config.LEASE_SECONDS)},
                 synchronize_session=False))
    db.commit()
    return n == 1


def build_body(event: models.Event) -> bytes:
    return json.dumps({
        "id": event.public_id,
        "type": event.event_type,
        "timestamp": _aware(event.created_at).isoformat(),
        "data": event.payload,
    }, separators=(",", ":")).encode()


def _refresh_event_status(db, event_id: int):
    db.flush()   # sessions use autoflush=False: make this delivery's new state visible to the query
    # Lock the event row so two deliveries finishing concurrently can't write stale status.
    event = db.query(models.Event).filter(models.Event.id == event_id).with_for_update().one()
    statuses = [s for (s,) in db.query(models.Delivery.status)
                .filter(models.Delivery.event_id == event_id).all()]
    if any(s not in TERMINAL for s in statuses):
        event.status = "processing"
    elif any(s == "dead_letter" for s in statuses):
        event.status = "failed"
    else:
        event.status = "delivered"


def attempt_delivery(session_factory, delivery_id: int, request_id: Optional[str] = None,
                     http=requests, redis_client=None, traceparent: Optional[str] = None) -> str:
    """Runs one attempt inside a `delivery.attempt` span that is a child of the ingest request's
    trace (traceparent travelled outbox -> stream), so ingest, every retry and the HTTP call are
    one trace. Returns the outcome: skipped | busy | success | retry_scheduled | dead_letter | cancelled."""
    with tracer().start_as_current_span(
            "delivery.attempt", context=context_from_traceparent(traceparent),
            attributes={"ferrum.delivery_id": delivery_id}) as span:
        outcome = _attempt_delivery(session_factory, delivery_id, request_id, http, redis_client)
        span.set_attribute("ferrum.outcome", outcome)
        return outcome


def _attempt_delivery(session_factory, delivery_id, request_id, http, redis_client) -> str:
    db = session_factory()
    try:
        now = datetime.now(timezone.utc)
        if not _claim(db, delivery_id, now):
            current = db.get(models.Delivery, delivery_id)
            if current is not None and current.status == "in_flight":
                # Another worker holds a live lease. Don't ack: if that worker dies, the message
                # is reclaimed and the stale lease can then be taken over.
                return "busy"
            DUPLICATES_SKIPPED.inc()
            logger.info("delivery_skipped", extra={"service": "worker", "request_id": request_id,
                                                   "delivery_id": delivery_id})
            return "skipped"

        delivery = db.get(models.Delivery, delivery_id)
        event = db.get(models.Event, delivery.event_id)
        webhook = db.get(models.Webhook, delivery.webhook_id)
        log = {"service": "worker", "request_id": request_id,
               "event_id": event.public_id, "delivery_id": delivery_id}
        span = trace.get_current_span()
        span.set_attribute("ferrum.event_id", event.public_id)

        if webhook is None or webhook.deleted_at is not None:
            delivery.status = "cancelled"
            delivery.locked_until = None
            _refresh_event_status(db, event.id)
            db.commit()
            logger.info("delivery_cancelled", extra=log)
            return "cancelled"

        attempt_no = (delivery.retries or 0) + 1
        if attempt_no == 1:
            QUEUE_DELAY.observe((now - _aware(event.created_at)).total_seconds())

        body = build_body(event)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Ferrum-Webhooks/1.0",
            # stable across retries and replays: this is the dedupe key for the receiver
            **webhook_headers(webhook.secret, event.public_id, body),
        }

        code = latency_ms = error = None
        permanent = False
        start = time.time()
        host = urlsplit(webhook.url).hostname
        with tracer().start_as_current_span("webhook.post",
                                            attributes={"server.address": host or "",
                                                        "ferrum.attempt": attempt_no}) as hspan:
            try:
                check_url(webhook.url)       # re-check at send time: DNS may have changed (rebinding)
                resp = http.post(webhook.url, data=body, headers=headers, allow_redirects=False,
                                 timeout=(config.HTTP_CONNECT_TIMEOUT, config.HTTP_READ_TIMEOUT))
                code = resp.status_code
                ok = 200 <= code < 300
                if not ok:
                    error = f"HTTP {code}"
                hspan.set_attribute("http.response.status_code", code)
            except BlockedTarget as e:
                ok, permanent = False, True  # no point retrying a forbidden target
                error = f"blocked target: {e}"
            except Exception as e:   # timeout, DNS failure, connection refused, TLS ...
                ok = False
                error = f"{type(e).__name__}: {e}"[:500]
            if not ok:
                hspan.set_status(trace.Status(trace.StatusCode.ERROR, error))
        latency_ms = int((time.time() - start) * 1000)

        done = datetime.now(timezone.utc)
        db.add(models.DeliveryAttempt(delivery_id=delivery_id, attempt=attempt_no,
                                      status="success" if ok else "failed",
                                      response_code=code, latency_ms=latency_ms,
                                      error_message=error, attempted_at=done))
        delivery.attempted_at = done
        delivery.response_code = code
        delivery.latency_ms = latency_ms
        delivery.error_message = error
        delivery.locked_until = None
        delivery.retries = attempt_no
        dead_lettered = False

        if ok:
            delivery.status = "success"
            delivery.next_retry_at = None
            DELIVERY_SUCCESS.inc()
            DELIVERY_LATENCY.observe(latency_ms / 1000)
            END_TO_END_LATENCY.observe((done - _aware(event.created_at)).total_seconds())
            outcome = "success"
        else:
            DELIVERY_FAILURE.inc()
            if permanent or attempt_no >= config.MAX_ATTEMPTS:
                delivery.status = "dead_letter"
                delivery.moved_to_dlq = 1
                delivery.next_retry_at = None
                DLQ_EVENTS.inc()
                dead_lettered = True
                outcome = "dead_letter"
            else:
                delay = backoff_seconds(attempt_no)
                delivery.status = "retrying"
                delivery.next_retry_at = done + timedelta(seconds=delay)
                RETRY_ATTEMPTS.inc()
                log["retry_in"] = round(delay, 1)
                outcome = "retry_scheduled"

        _refresh_event_status(db, event.id)
        db.commit()   # <- the DB write; the caller XACKs only after this returns

        logger.log(logging.INFO if ok else logging.WARNING, "delivery_" + outcome,
                   extra={**log, "attempt": attempt_no, "status_code": code,
                          "latency": latency_ms, "error": error})
        if dead_lettered and redis_client is not None:
            try:
                redis_client.xadd(config.DLQ_STREAM, {
                    "delivery_id": delivery_id, "event_id": event.public_id,
                    "webhook_id": delivery.webhook_id, "error": error or ""})
            except Exception as e:  # DLQ stream is a convenience copy; the DB row is the record
                logger.error("dlq_push_error", extra={**log, "error": str(e)})
        return outcome
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
