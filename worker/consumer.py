# file: worker/consumer.py
#
# Redis Streams consumer group.
#   XREADGROUP  new messages            -> process -> DB commit -> XACK (+XDEL)
#   XAUTOCLAIM  messages pending too long (crashed/stalled consumer) are taken over and retried
# A crash anywhere before XACK leaves the message in the group's pending list, so nothing is lost.

import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import redis

from app.metrics import EVENTS_PROCESSED, STREAM_RECLAIMED
from worker import config
from worker.delivery import attempt_delivery

logger = logging.getLogger(__name__)

CONSUMER_NAME = os.getenv("HOSTNAME", socket.gethostname()) + "-" + str(os.getpid())


def ensure_group(r):
    try:
        r.xgroup_create(config.STREAM, config.GROUP, id="0", mkstream=True)
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def _ack(r, msg_id: str):
    pipe = r.pipeline()
    pipe.xack(config.STREAM, config.GROUP, msg_id)
    pipe.xdel(config.STREAM, msg_id)      # single group => acked entries are garbage
    pipe.execute()


def handle_message(session_factory, r, msg_id: str, fields: dict, http=None):
    """Process one message. Acks only after the delivery's DB state is committed."""
    EVENTS_PROCESSED.inc()
    try:
        delivery_id = int(fields["delivery_id"])
    except (KeyError, ValueError):
        logger.error("malformed_message", extra={"service": "worker", "msg_id": msg_id})
        r.xadd(config.DLQ_STREAM, {"msg_id": msg_id, "reason": "malformed", **fields})
        _ack(r, msg_id)
        return
    kwargs = {"http": http} if http is not None else {}
    outcome = attempt_delivery(session_factory, delivery_id,
                               request_id=fields.get("request_id") or None,
                               traceparent=fields.get("traceparent") or None,
                               redis_client=r, **kwargs)
    if outcome != "busy":
        _ack(r, msg_id)


def _is_poison(r, msg_id: str) -> bool:
    info = r.xpending_range(config.STREAM, config.GROUP, min=msg_id, max=msg_id, count=1)
    return bool(info) and info[0]["times_delivered"] > config.MAX_MESSAGE_DELIVERIES


def reclaim_stale(r, consumer: str = CONSUMER_NAME, count: int = 50):
    """XAUTOCLAIM everything idle longer than RECLAIM_IDLE_MS. Returns [(id, fields)]."""
    claimed, cursor = [], "0-0"
    while True:
        res = r.xautoclaim(config.STREAM, config.GROUP, consumer,
                           min_idle_time=config.RECLAIM_IDLE_MS, start_id=cursor, count=count)
        cursor, messages = res[0], res[1]          # Redis 7 adds a 3rd element (deleted ids)
        claimed.extend((mid, f) for mid, f in messages if f)
        for mid, f in messages:
            if not f:                               # entry was XDEL'd; drop the dangling pending ref
                r.xack(config.STREAM, config.GROUP, mid)
        if cursor in ("0-0", b"0-0") or not messages:
            break
    if claimed:
        STREAM_RECLAIMED.inc(len(claimed))
        logger.warning("stream_messages_reclaimed",
                       extra={"service": "worker", "count": len(claimed)})
    return claimed


def run_batch(session_factory, r, executor, messages, http=None, check_poison=False):
    futures = []
    for msg_id, fields in messages:
        if check_poison and _is_poison(r, msg_id):
            logger.error("poison_message_dropped", extra={"service": "worker", "msg_id": msg_id})
            r.xadd(config.DLQ_STREAM, {"msg_id": msg_id, "reason": "poison", **fields})
            _ack(r, msg_id)
            continue
        futures.append((msg_id, executor.submit(handle_message, session_factory, r,
                                                msg_id, fields, http)))
    for msg_id, fut in futures:
        try:
            fut.result()
        except Exception as e:
            # No ack: it stays pending and XAUTOCLAIM hands it out again after RECLAIM_IDLE_MS.
            logger.error("message_failed_will_be_reclaimed",
                         extra={"service": "worker", "msg_id": msg_id, "error": str(e)})


def consume_loop(session_factory, r, shutdown: threading.Event, heartbeat, http=None,
                 consumer: str = CONSUMER_NAME):
    ensure_group(r)
    logger.info("consumer_started", extra={"service": "worker", "consumer": consumer})
    last_reclaim = 0.0
    with ThreadPoolExecutor(max_workers=config.CONCURRENCY) as executor:
        while not shutdown.is_set():
            heartbeat()
            try:
                if time.monotonic() - last_reclaim >= config.RECLAIM_INTERVAL_SECONDS:
                    last_reclaim = time.monotonic()
                    stale = reclaim_stale(r, consumer)
                    if stale:
                        run_batch(session_factory, r, executor, stale, http, check_poison=True)

                resp = r.xreadgroup(config.GROUP, consumer, {config.STREAM: ">"},
                                    count=config.CONCURRENCY, block=2000)
                if resp:
                    run_batch(session_factory, r, executor, resp[0][1], http)
            except redis.exceptions.ResponseError as e:
                if "NOGROUP" in str(e):          # Redis was flushed/failed over: recreate the group
                    ensure_group(r)
                else:
                    logger.error("redis_error", extra={"service": "worker", "error": str(e)})
                    shutdown.wait(1)
            except redis.exceptions.RedisError as e:
                logger.error("redis_error", extra={"service": "worker", "error": str(e)})
                shutdown.wait(1)
            except Exception as e:
                logger.error("consumer_loop_error", extra={"service": "worker", "error": str(e)})
                shutdown.wait(1)
    logger.info("consumer_stopped", extra={"service": "worker"})
