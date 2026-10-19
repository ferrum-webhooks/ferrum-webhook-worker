from prometheus_client import Counter, Histogram

EVENTS_PROCESSED = Counter(
    "worker_events_processed_total",
    "Total deliveries picked up from the stream"
)

DELIVERY_SUCCESS = Counter(
    "worker_delivery_success_total",
    "Successful deliveries"
)

DELIVERY_FAILURE = Counter(
    "worker_delivery_failure_total",
    "Failed delivery attempts"
)

DELIVERY_LATENCY = Histogram(
    "worker_delivery_latency_seconds",
    "Webhook delivery latency"
)

QUEUE_DELAY = Histogram(
    "worker_queue_delay_seconds",
    "Time between event creation and the first delivery attempt"
)

END_TO_END_LATENCY = Histogram(
    "worker_end_to_end_latency_seconds",
    "Total time from event creation to successful delivery"
)

RETRY_ATTEMPTS = Counter(
    "worker_retry_attempts_total",
    "Retries scheduled"
)

DLQ_EVENTS = Counter(
    "worker_dlq_events_total",
    "Deliveries moved to dead letter"
)

OUTBOX_PUBLISHED = Counter(
    "worker_outbox_published_total",
    "Outbox rows relayed to the stream"
)

STREAM_RECLAIMED = Counter(
    "worker_stream_reclaimed_total",
    "Stream messages reclaimed from crashed/stalled consumers (XAUTOCLAIM)"
)

DUPLICATES_SKIPPED = Counter(
    "worker_duplicate_messages_skipped_total",
    "Stream messages skipped because the delivery was already handled"
)
