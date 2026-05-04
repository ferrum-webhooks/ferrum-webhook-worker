from prometheus_client import Counter, Histogram

EVENTS_PROCESSED = Counter(
    "worker_events_processed_total",
    "Total events processed"
)

DELIVERY_SUCCESS = Counter(
    "worker_delivery_success_total",
    "Successful deliveries"
)

DELIVERY_FAILURE = Counter(
    "worker_delivery_failure_total",
    "Failed deliveries"
)

DELIVERY_LATENCY = Histogram(
    "worker_delivery_latency_seconds",
    "Webhook delivery latency"
)