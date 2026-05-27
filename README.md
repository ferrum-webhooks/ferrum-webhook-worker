# Ferrum — Webhook Worker Service (Phase 6)

## Overview

This repository contains the **Worker Service** of Ferrum — a cloud-native webhook relay system.

The worker is responsible for:

| Responsibility              | Description                        |
| --------------------------- | ---------------------------------- |
| Queue consumption           | pulls events from Redis            |
| Webhook delivery            | sends outbound webhook requests    |
| Delivery tracking           | records success/failure state      |
| Retry scheduling            | retries failed deliveries          |
| DLQ handling                | captures permanently failed events |
| Metrics instrumentation     | exposes operational metrics        |
| Queue latency tracking      | measures backlog pressure          |
| End-to-end latency tracking | measures total processing delay    |
| Structured logging          | operational debugging              |


Ferrum Worker is the asynchronous event processing and webhook delivery engine for the Ferrum platform.

The worker evolved from a simple Redis consumer into a production-oriented distributed background processing system implementing:

* asynchronous event consumption
* Redis queue processing
* webhook delivery orchestration
* retry scheduling
* dead letter queue handling
* Prometheus instrumentation
* Kubernetes autoscaling
* structured logging
* resilience engineering
* graceful shutdown
* production-safe lifecycle management

---

## Architecture Context

```text
                ┌────────────────────┐
                │      Gateway       │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │    Redis Queue     │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │      Worker        │
                │ Async Consumer     │
                └─────────┬──────────┘
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
 ┌────────────────┐             ┌────────────────┐
 │ PostgreSQL DB  │             │ External Hooks │
 └────────────────┘             └────────────────┘
```
---


# Final Worker Capabilities

## Queue Processing

* Redis BRPOP consumption
* asynchronous event handling
* producer-consumer architecture
* distributed workload execution

---

## Delivery Management

* outbound webhook delivery
* delivery latency tracking
* success/failure recording
* response code tracking
* timeout handling

---

## Reliability Features

* retry scheduling
* dead letter queue
* transient failure recovery
* queue buffering
* graceful shutdown
* rolling deployment safety

---

## Observability Features

* Prometheus metrics
* queue delay histograms
* end-to-end latency measurement
* delivery success counters
* delivery failure counters
* structured logs
* request correlation IDs

---

## Infrastructure Features

* Kubernetes deployments
* autoscaling
* readiness/liveness probes
* startup probes
* PodDisruptionBudgets
* resource requests/limits
* rolling updates

---

# Core Technology Stack

| Layer            | Technology           |
| ---------------- | -------------------- |
| Runtime          | Python 3.11          |
| Queue            | Redis                |
| Database         | PostgreSQL           |
| ORM              | SQLAlchemy           |
| Metrics          | Prometheus           |
| Containerization | Docker               |
| Orchestration    | Kubernetes           |
| Load Testing     | k6                   |
| Logging          | structured JSON logs |
| CI/CD            | GitHub Actions       |

---

# Final Operational Metrics

The worker processed sustained distributed traffic during Phase 8 load testing.

## Measured Performance

| Metric                   | Result      |
| ------------------------ | ----------- |
| Concurrent virtual users | 50          |
| Total processed requests | 8,179       |
| Sustained throughput     | 135 req/sec |
| Request failure rate     | 0%          |
| Average API latency      | 368ms       |
| p95 latency              | 704ms       |
| Maximum latency          | 2.21s       |

---

# Autoscaling Behavior

Under CPU pressure:

## Worker scaled automatically:

```text
1 pod → 2 pods
```

Kubernetes successfully:

* detected worker CPU pressure
* scheduled new worker replicas
* balanced distributed queue consumption
* scaled back down after load subsided

---

# Core Worker Metrics

The worker exposed operational metrics through Prometheus.

## Throughput Metrics

```promql
worker_events_processed_total
```

Measures:

* total processed events
* worker throughput
* consumption rate

---

## Queue Delay Metrics

```promql
worker_queue_delay_seconds_sum /
worker_queue_delay_seconds_count
```

Measures:

* queue congestion
* processing lag
* consumer pressure

---

## Delivery Latency Metrics

```promql
worker_delivery_latency_seconds
```

Measures:

* outbound webhook performance
* downstream responsiveness

---

## End-to-End Latency

```promql
worker_end_to_end_latency_seconds
```

Measures:

* total system processing delay
* full event lifecycle timing

---

# Quantitative Improvements Across Phases

# Async Queue Processing Improvements

Before queue architecture:

```text
Gateway handled webhook delivery synchronously
```

Problems:

* client requests blocked on webhook delivery
* downstream failures propagated directly
* poor scalability
* long request times
* no buffering capability

---

After worker architecture:

```text
Gateway → Redis → Worker → Webhook
```

Effects:

| Improvement         | Result                       |
| ------------------- | ---------------------------- |
| Request decoupling  | gateway returned immediately |
| Burst absorption    | Redis buffered spikes        |
| Failure isolation   | webhook failures isolated    |
| Independent scaling | workers scaled separately    |
| Throughput increase | sustained 135 req/sec        |

---

# Retry System Improvements

Before retry logic:

* failed deliveries lost permanently
* transient outages caused data loss
* no recovery behavior

---

After retry implementation:

| Feature                      | Result                          |
| ---------------------------- | ------------------------------- |
| Retry scheduling             | transient failures recovered    |
| Controlled retries           | prevented retry storms          |
| Persistent delivery tracking | operational visibility          |
| Failure observability        | measurable delivery reliability |

---

# Dead Letter Queue Improvements

Before DLQ:

* exhausted retries disappeared silently
* permanent failures invisible
* no operational recovery path

---

After DLQ:

| Capability             | Result                      |
| ---------------------- | --------------------------- |
| Failure preservation   | failed events retained      |
| Recovery workflows     | replay possible             |
| Operational debugging  | payload inspection possible |
| Reliability guarantees | failure accountability      |

---

# Observability Improvements

Before instrumentation:

```text
No queue visibility
No throughput visibility
No latency visibility
No delivery visibility
```

---

After Prometheus integration:

Measured:

* queue delays
* event throughput
* delivery success/failure ratios
* processing latency
* end-to-end latency
* worker CPU pressure

---

# Failure Injection Results

Phase 9 introduced deliberate distributed-system failures.

## Injected Failures

| Failure                  | Observed Result                         |
| ------------------------ | --------------------------------------- |
| Worker pod deletion      | Kubernetes recreated pods automatically |
| Redis outage             | queue stalled safely                    |
| PostgreSQL outage        | worker failed predictably               |
| Slow webhook             | queue delay metrics increased           |
| Downstream 500 responses | retries triggered                       |
| Retry exhaustion         | DLQ captured failed events              |

---

# Structured Logging

The worker implemented structured JSON logging.

Example:

```json
{
  "service": "worker",
  "request_id": "uuid",
  "event_id": 42,
  "webhook_url": "https://example.com",
  "status_code": 500,
  "latency": 213
}
```

Benefits:

* distributed traceability
* operational debugging
* request correlation
* searchable logs
* failure diagnostics

---

# Final Production Readiness Features

## Health Probes

Implemented:

* readinessProbe
* livenessProbe
* startupProbe

Worker probes target:

```text
/metrics
```

Effects:

* unhealthy workers restarted automatically
* traffic only routed to healthy consumers
* slow startup workers protected from premature kills

---

# Graceful Shutdown

Implemented:

```yaml
preStop:
  exec:
    command: ["/bin/sh", "-c", "sleep 10"]
```

Effects:

* in-flight processing completed safely
* scale-down events became safer
* rolling deployments avoided abrupt interruption

---

# Deployment Safety

Implemented:

```yaml
maxUnavailable: 0
maxSurge: 1
```

Effects:

* safe rolling deployments
* zero-downtime updates
* healthy worker capacity maintained during rollouts

---

# Resource Management

Implemented:

```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "256Mi"
    cpu: "500m"
```

Effects:

* HPA compatibility
* predictable scheduling
* safer cluster behavior
* controlled resource consumption

---

# End-to-End Reliability Characteristics

By Phase 10, the worker implemented:

| Capability                        | Status |
| --------------------------------- | ------ |
| Async event processing            | ✅      |
| Queue buffering                   | ✅      |
| Retry handling                    | ✅      |
| Dead letter queue                 | ✅      |
| Structured logging                | ✅      |
| Prometheus instrumentation        | ✅      |
| Autoscaling                       | ✅      |
| Graceful shutdown                 | ✅      |
| Rolling deployment safety         | ✅      |
| Kubernetes orchestration          | ✅      |
| Failure recovery                  | ✅      |
| Health probe lifecycle management | ✅      |

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
  * pytest

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

# Phase-by-Phase Breakdown

# Phase 1 — Initial API Platform

## Goal

Build the initial webhook platform foundation.

---

## Worker State

At this stage:

```text
No worker existed yet
```

Webhook delivery occurred synchronously inside the gateway.

---

## System Problems

* blocking request lifecycle
* downstream webhook latency affected clients
* no scalability separation
* no buffering

---

# Phase 2 — Persistence Layer

## Goal

Introduce durable delivery tracking.

---

## Implemented

* Event model
* Delivery model
* PostgreSQL persistence
* delivery status tracking

---

## Concepts Learned

| Concept             | Description                  |
| ------------------- | ---------------------------- |
| persistence         | durable event storage        |
| delivery state      | operational visibility       |
| relational modeling | event-delivery relationships |

---

# Phase 3 — Worker + Redis Queue Architecture

## Goal

Introduce asynchronous processing.

---

## Implemented

* Redis queue
* BRPOP consumption loop
* dedicated worker service
* async delivery pipeline

---

## Architectural Shift

Before:

```text
Gateway directly sends webhook
```

After:

```text
Gateway publishes event → worker consumes asynchronously
```

---

## Concepts Learned

| Concept                   | Description            |
| ------------------------- | ---------------------- |
| asynchronous systems      | decoupled workloads    |
| queues                    | burst buffering        |
| event-driven architecture | distributed processing |
| producer-consumer systems | async coordination     |

---

# Phase 4 — Dockerization

## Goal

Containerize worker infrastructure.

---

## Implemented

* Dockerfile
* Compose integration
* environment injection
* service networking

---

## Concepts Learned

| Concept         | Description                   |
| --------------- | ----------------------------- |
| containers      | isolated runtime environments |
| networking      | inter-service communication   |
| reproducibility | deterministic execution       |

---

# Phase 5 — Observability

## Goal

Instrument worker runtime behavior.

---

## Implemented

* Prometheus metrics
* queue delay histograms
* delivery counters
* processing metrics
* end-to-end latency metrics

---

## Key Metrics

```promql
worker_events_processed_total
```

```promql
worker_queue_delay_seconds
```

```promql
worker_end_to_end_latency_seconds
```

---

## Concepts Learned

| Concept                | Description            |
| ---------------------- | ---------------------- |
| observability          | operational visibility |
| latency analysis       | distributed timing     |
| throughput measurement | processing visibility  |
| queue analysis         | backlog monitoring     |

---

# Phase 6 — CI/CD + GHCR

## Goal

Automate builds and deployments.

---

## Implemented

* GitHub Actions
* Docker image builds
* GHCR publishing
* immutable deployments

---

## Concepts Learned

| Concept                  | Description           |
| ------------------------ | --------------------- |
| CI/CD                    | automated delivery    |
| image registries         | artifact distribution |
| immutable infrastructure | reproducible releases |

---

# Phase 7 — Kubernetes Migration

## Goal

Move worker infrastructure to Kubernetes.

---

## Implemented

* Deployments
* Services
* ConfigMaps
* Secrets
* PVC integration
* namespace isolation

---

## Concepts Learned

| Concept                    | Description                    |
| -------------------------- | ------------------------------ |
| orchestration              | distributed runtime management |
| declarative infrastructure | desired state systems          |
| pod lifecycle              | execution semantics            |
| service abstraction        | cluster networking             |

---

# Phase 8 — Autoscaling + Load Testing

## Goal

Validate distributed queue processing under load.

---

## Implemented

* HPA autoscaling
* CPU-based scaling
* k6 distributed load tests
* throughput measurement

---

## Measured Results

| Metric             | Result      |
| ------------------ | ----------- |
| Throughput         | 135 req/sec |
| Requests processed | 8,179       |
| Failed requests    | 0%          |
| Worker scaling     | 1 → 2 pods  |

---

## Concepts Learned

| Concept               | Description              |
| --------------------- | ------------------------ |
| autoscaling           | elastic infrastructure   |
| distributed workloads | parallel consumers       |
| load testing          | runtime validation       |
| resource scheduling   | Kubernetes orchestration |

---

# Phase 9 — Failure Injection + Resilience

## Goal

Force real distributed-system failures.

---

## Implemented

* retry system
* dead letter queue
* structured logging
* failure injection tests
* queue pressure validation

---

## Injected Failures

| Failure                 | Result                      |
| ----------------------- | --------------------------- |
| Worker crash            | pod recreated automatically |
| Redis outage            | consumption stalled safely  |
| PostgreSQL outage       | predictable failure state   |
| Slow downstream service | queue delays increased      |
| Delivery failures       | retries scheduled           |
| Retry exhaustion        | DLQ capture                 |

---

## Concepts Learned

| Concept                | Description             |
| ---------------------- | ----------------------- |
| cascading failures     | distributed instability |
| retry storms           | failure amplification   |
| resilience engineering | fault recovery          |
| operational recovery   | reliability design      |

---

# Phase 10 — Production Readiness

## Goal

Stabilize worker infrastructure for production operation.

---

## Implemented

* readiness probes
* liveness probes
* startup probes
* graceful shutdown
* rolling deployments
* PodDisruptionBudgets
* resource tuning

---

## Concepts Learned

| Concept                  | Description              |
| ------------------------ | ------------------------ |
| health semantics         | availability gating      |
| graceful draining        | in-flight request safety |
| deployment orchestration | safe rollouts            |
| operational stability    | production reliability   |

---

# Final Engineering Outcome

The worker evolved from:

```text
No asynchronous processing
```

into:

```text
Distributed resilient background delivery engine
```

The final system demonstrates practical understanding of:

* asynchronous architecture
* distributed queues
* event-driven systems
* observability engineering
* resilience engineering
* autoscaling
* Kubernetes orchestration
* operational reliability
* production-safe deployments
* failure recovery systems

---

# Final Status

## Completed

✅ Redis queue processing

✅ Async webhook delivery

✅ Delivery tracking

✅ Retry scheduling

✅ Dead letter queue

✅ Structured logging

✅ Prometheus instrumentation

✅ Kubernetes orchestration

✅ Horizontal autoscaling

✅ Failure injection testing

✅ Graceful shutdown

✅ Rolling deployments

✅ Health probes

✅ Production-safe lifecycle management

---

# Future Extensions

Potential future improvements:

* exponential backoff retry tuning
* distributed tracing
* OpenTelemetry
* Kafka migration
* RabbitMQ support
* webhook batching
* webhook signing
* adaptive retry scheduling
* canary deployments
* Grafana dashboards
* circuit breakers
* rate limiting
* SLO/SLA management
* cloud-managed Kubernetes
* service mesh integration
