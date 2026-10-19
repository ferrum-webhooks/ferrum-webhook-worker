# file: worker/config.py

import os

import redis

STREAM = os.getenv("STREAM_NAME", "deliveries:stream")
GROUP = os.getenv("STREAM_GROUP", "delivery-workers")
DLQ_STREAM = os.getenv("DLQ_STREAM_NAME", "deliveries:dlq")

MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", 5))
RETRY_BASE_SECONDS = float(os.getenv("RETRY_BASE_SECONDS", 5))     # 5s, 10s, 20s, 40s ...
RETRY_MAX_SECONDS = float(os.getenv("RETRY_MAX_SECONDS", 3600))
RETRY_JITTER = float(os.getenv("RETRY_JITTER", 0.2))               # +/-20%

HTTP_CONNECT_TIMEOUT = float(os.getenv("HTTP_CONNECT_TIMEOUT", 3))
HTTP_READ_TIMEOUT = float(os.getenv("HTTP_READ_TIMEOUT", 5))

# A claimed delivery that is still `in_flight` after this long is presumed orphaned.
LEASE_SECONDS = int(os.getenv("LEASE_SECONDS", 60))
# A stream message pending (unacked) this long is reclaimed from its consumer via XAUTOCLAIM.
RECLAIM_IDLE_MS = int(os.getenv("RECLAIM_IDLE_MS", 90_000))   # must exceed LEASE_SECONDS
RECLAIM_INTERVAL_SECONDS = float(os.getenv("RECLAIM_INTERVAL_SECONDS", 15))
MAX_MESSAGE_DELIVERIES = int(os.getenv("MAX_MESSAGE_DELIVERIES", 10))   # poison-message cutoff

CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", 8))
RELAY_INTERVAL_SECONDS = float(os.getenv("RELAY_INTERVAL_SECONDS", 0.2))
RELAY_BATCH = int(os.getenv("RELAY_BATCH", 200))
SCHEDULER_INTERVAL_SECONDS = float(os.getenv("SCHEDULER_INTERVAL_SECONDS", 1))
# A delivery still `pending` this long after its outbox row was published has probably lost its stream
# message (Redis flushed/failed over): re-enqueue it. Kept large so a normal backlog does not trigger it.
STALE_PENDING_SECONDS = int(os.getenv("STALE_PENDING_SECONDS", 900))
OUTBOX_RETENTION_SECONDS = int(os.getenv("OUTBOX_RETENTION_SECONDS", 86400))

HEALTH_PORT = int(os.getenv("HEALTH_PORT", 8001))
HEALTH_STALE_SECONDS = float(os.getenv("HEALTH_STALE_SECONDS", 60))


def make_redis() -> "redis.Redis":
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=0,
        decode_responses=True,
        socket_connect_timeout=2,
        # must exceed the XREADGROUP block time (2s) or every idle poll would time out
        socket_timeout=10,
        health_check_interval=15,
    )
