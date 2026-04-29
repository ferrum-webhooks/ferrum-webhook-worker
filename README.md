# Ferrum — Webhook Worker Service (Phase 3)

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

Ferrum is now composed of two services:

### 1. Gateway (`webhook-gateway`)

* Accepts API requests
* Stores events in database
* Pushes events to queue

### 2. Worker (`webhook-worker`) ← *this repo*

* Consumes events from queue
* Fetches event + webhook data from DB
* Delivers webhook via HTTP POST
* Stores delivery result

---

## System Flow

Client → Gateway → PostgreSQL → Redis Queue → Worker → Webhook Endpoint

---

## Responsibilities

### Worker DOES:

* Consume events from Redis queue
* Fetch event from database
* Find matching webhooks
* Send HTTP POST requests
* Measure latency
* Store delivery results

### Worker DOES NOT:

* Accept HTTP requests
* Authenticate users
* Manage webhooks
* Perform retries (yet)
* Guarantee exactly-once delivery

---

## Project Structure

```text
webhook-worker/
  worker/
    main.py        # Worker loop and processing logic
  app/
    db.py          # DB connection and session
    models.py      # Shared SQLAlchemy models
  requirements.txt
  README.md
```

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

---

## Setup Instructions

### 1. Clone repository

```bash
git clone <your-repo-url>
cd webhook-worker
```

---

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

---

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Configure environment

Ensure:

* PostgreSQL is running
* Redis is running on:

```text
localhost:6379
```

---

### 5. Run worker

```bash
python worker/main.py
```

Expected output:

```text
Worker started. Waiting for events...
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
Received event: {"event_id": 1}
Found 1 webhooks
Delivered to https://webhook.site/... [200]
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

### Logging

Logs include:

* event consumption
* webhook count
* delivery status
* errors

---

### Latency Measurement

Latency is calculated per delivery:

```text
latency_ms = time_taken_for_http_request
```

---

## Failure Handling (Current State)

### Implemented:

* Exception handling in worker loop
* Delivery failure logging

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

## Deliberate Gaps (Phase 4+ Work)

These are intentionally deferred:

* Retry system with exponential backoff
* Delivery attempt tracking (`delivery_attempts` table)
* Dead letter queue
* Idempotency enforcement
* Async HTTP client
* Queue durability improvements (e.g., RabbitMQ/Kafka)
* Horizontal worker scaling

---

## Key Concepts Demonstrated

* Event-driven architecture
* Producer-consumer model
* Asynchronous processing
* Decoupling of services
* Queue-based communication

---

## Status

🚧 Phase 3 — In Progress
✅ Gateway → Queue → Worker pipeline operational

---

## Next Steps

* Implement retry mechanism
* Introduce backoff strategy
* Add delivery attempt tracking
* Improve failure resilience

---

## Summary

The system has successfully transitioned from:

```text
Synchronous request-response
```

to:

```text
Asynchronous event-driven architecture
```

This forms the foundation for:

* scalability
* fault tolerance
* real-world webhook delivery systems
