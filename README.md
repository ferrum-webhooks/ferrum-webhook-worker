# Ferrum — Webhook Worker Service (Phase 5)

## Overview

This repository contains the **Worker Service** of Ferrum — a cloud-native webhook relay system.

The worker is responsible for:

* consuming events from a queue
* processing them asynchronously
* delivering them to registered webhook endpoints
* recording delivery outcomes

This service marks the transition from a synchronous system to an **event-driven architecture**.

---

## Architecture Context

```
Client → Gateway → PostgreSQL → Redis Queue → Worker → Webhook Endpoint
```
---

## Responsibilities

### Worker DOES:

* Consume events from Redis queue
* Fetch event from database
* Find matching webhooks
* Send HTTP POST requests
* Measure latency
* Store delivery results
* Emit structured logs and metrics

### Worker DOES NOT:

* Accept HTTP requests
* Authenticate users
* Manage webhooks
* Perform retries (yet)
* Guarantee exactly-once delivery

---

## Dependencies

* Python 3.10+
* Redis
* PostgreSQL
* Python packages:

  * redis
  * sqlalchemy
  * psycopg2-binary
  * requests
  * prometheus client
  * python-json-logger

---

## Setup Instructions

### 1. Clone repository

```bash
git clone <your-repo-url>
cd webhook-worker
```

---

### 2. Configure environment

```text
DB_HOST 
DB_PORT 
DB_USER 
DB_PASSWORD 
DB_NAME 
REDIS_HOST 
REDIS_PORT
```

---

### 5. Run in Docker

```bash
docker build -t ferrum-worker .
docker run ferrum-worker
```

---

## End-to-End Testing

### Step 1 — Start all services

* Redis
* PostgreSQL
* Gateway (`uvicorn`)
* Worker

---

### Step 2 — Register webhook

Use a test endpoint such as webhook.site:

```bash
curl -X POST http://127.0.0.1:8000/webhooks \
-H "Content-Type: application/json" \
-d '{"url": "https://webhook.site/your-id", "event_type": "test"}'
```

---

### Step 3 — Send event

```bash
curl -X POST http://127.0.0.1:8000/events \
-H "Content-Type: application/json" \
-d '{"payload": {"msg": "hello"}, "event_type": "test"}'
```

---

### Step 4 — Observe worker logs

```text
{
  "service": "worker",
  "event": "delivery_result",
  "event_id": 1,
  "request_id": "abc-123",
  "status_code": 200,
  "latency": 0.12
}
```

---

### Step 5 — Verify delivery

* Visit webhook.site
* Confirm payload received

---

## Internal Workflow

### 1. Queue Consumption

* Redis LIST used as queue
* Blocking read via `BRPOP`
* Ensures worker waits efficiently

---

### 2. Event Processing

* Fetch event using `event_id`
* Query matching webhooks by `event_type`

---

### 3. Delivery

* HTTP POST to webhook URL
* JSON payload sent
* Timeout: 5 seconds

---

### 4. Tracking

Each delivery is stored in `deliveries` table:

* status (success / failed)
* response_code
* latency_ms

---

## Observability

### Request Correlation

Each event carries:
```
request_id
```
Flow:
```
Gateway → Queue → Worker → Delivery logs
```
This enables end-to-end tracing of a single request.

### Logging

Structured JSON logs include:

* event_received
* delivery_attempt
* delivery_result
* delivery_failed

Fields:
```
service, event_id, request_id, latency, status_code, error
```

### Metrics (Prometheus)

Worker exposes metrics at:
```
http://localhost:8001/metrics
```

### Core Metrics
* `worker_events_processed_total`
* `worker_delivery_success_total`
* `worker_delivery_failure_total`
* `worker_delivery_latency_seconds`

### Advanced Metrics
* Queue Delay
```worker_queue_delay_seconds```

* Measures:

```time between event creation and worker processing```

### End-to-End Latency
```worker_end_to_end_latency_seconds```

* Measures:
```
event creation → webhook delivery completion
```


#### Important Note on Histograms

Metrics expose:

* `_bucket`
* `_sum`
* `_count`

To compute averages:
```
sum / count
```
To compute percentiles:
```
histogram_quantile(...)
```
## Failure Handling (Current State)

### Implemented:

* Exception handling in worker loop
* Delivery failure logging
* Metrics for failure tracking

### Not Implemented (yet):

* Retry mechanism
* Exponential backoff
* Dead letter queue
* Idempotency guarantees

---

## Known Limitations

### 1. At-least-once NOT guaranteed yet

* Failures are not retried

### 2. No retry system

* Failed deliveries are dropped

### 3. No dead letter queue

* Failed events are not persisted for later recovery

### 4. No idempotency

* Duplicate deliveries possible in future

### 5. Blocking I/O

* HTTP calls are synchronous
* Limits throughput under load

### 6. Tight DB coupling

* Worker directly queries DB (acceptable for now)

### No distributed tracing
* Only `request_id` based tracking exists

---

## Design Decisions

### Why Redis LIST (not Streams)?

* Simpler mental model
* Easier debugging
* Sufficient for current phase

---

### Why fetch event from DB instead of queue payload?

* Avoid large messages
* Ensure consistency
* Keep queue lightweight

---

## Deliberate Gaps (Future Work)

These are intentionally deferred:

* Retry system with exponential backoff
* Delivery attempt tracking (`delivery_attempts` table)
* Dead letter queue
* Idempotency enforcement
* Async HTTP client
* Queue durability improvements (e.g., RabbitMQ/Kafka)
* Horizontal worker scaling
* Distributed Tracing (OpenTelemetry)
* Alterting and Dashboards (Grafana)

---

## Key Concepts Demonstrated

* Event-driven architecture
* Producer-consumer model
* Asynchronous processing
* Decoupling of services
* Queue-based communication
* Structured logging
* Metrics instrumentation (Prometheus)
* Queue delay analysis
* End-to-end latency tracking

---

## Status

🚧 Phase 5 — Observability
✅ Logs + Metrics + Correlation implemented
✅ End-to-end async processing working

---

## Next Steps

* Implement retry mechanism
* Introduce backoff strategy
* Add delivery attempt tracking
* Improve failure resilience

---
