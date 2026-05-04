# file: worker/main.py

from prometheus_client import start_http_server
from datetime import datetime, timezone
import json
import time
import redis
import requests
import logging
import os

from dotenv import load_dotenv

from app.db import SessionLocal
from app.logging_config import setup_logging
from app.metrics import (
    EVENTS_PROCESSED, DELIVERY_SUCCESS, DELIVERY_FAILURE, DELIVERY_LATENCY, QUEUE_DELAY, END_TO_END_LATENCY
)
from app import models

try:
    start_http_server(8001)
    logger.info("Metrics server started on port 8001")
except OSError:
    logger.warning("Metrics server already running on port 8001")

setup_logging()
logger = logging.getLogger(__name__)

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True
)

QUEUE_NAME = "event_queue"


def get_db():
    return SessionLocal()


def consume():
    logger.info("Worker started. Waiting for events...")

    while True:
        try:
            result = redis_client.brpop(QUEUE_NAME)
            if not result:
                continue

            _, data = result
            event_data = json.loads(data)

            logger.info(
                "event_received",
                extra={
                    "service": "worker",
                    "request_id": event_data.get("request_id"),
                    "event_id": event_data.get("event_id"),
                }
            )
            EVENTS_PROCESSED.inc()
            process_event(event_data)

        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            time.sleep(1)

def process_event(event_data: dict):
    db = get_db()

    try:
        event_id = event_data["event_id"]
        request_id = event_data.get("request_id")

        # Fetch event
        event = db.query(models.Event).filter(models.Event.id == event_id).first()

        if not event:
            logger.error(
                "event_not_found",
                extra={"service": "worker", "event_id": event_id}
            )
            return
        
        event_time = event.created_at
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        queue_delay = (now - event_time).total_seconds()
        QUEUE_DELAY.observe(queue_delay)
        logger.info(
            "queue_delay_computed",
            extra={
                "service": "worker",
                "request_id": request_id,
                "event_id": event_id,
                "queue_delay": round(queue_delay, 4),
            }
        )
        event.status = "processing"
        db.commit()

        # Fetch matching webhooks
        webhooks = db.query(models.Webhook).filter(
            models.Webhook.event_type == event.event_type
        ).all()

        all_success = True

        for webhook in webhooks:
            logger.info(
                "delivery_attempt",
                extra={
                    "service": "worker",
                    "request_id": request_id,
                    "event_id": event_id,
                    "webhook_url": webhook.url,
                }
            )
            success = deliver_event(db, event, webhook, request_id)
            if not success:
                all_success = False
        
        end_to_end_latency = (
            datetime.now(timezone.utc) - event_time
        ).total_seconds()
        END_TO_END_LATENCY.observe(end_to_end_latency)
        logger.info(
            "end_to_end_latency",
            extra={
                "service": "worker",
                "request_id": request_id,
                "event_id": event_id,
                "latency": round(end_to_end_latency, 4),
            }
        )

        event.status = "delivered" if all_success else "failed"
        db.commit()
    except Exception as e:
        logger.error(
            "event_processing_error",
            extra={
                "service": "worker",
                "request_id": request_id,
                "event_id": event_id,
                "error": str(e),
            }
        )
        if event:
            event.status = "failed"
            db.commit()
    finally:
        db.close()

def deliver_event(db, event, webhook, request_id):
    try:
        start = time.time()

        response = requests.post(
            webhook.url,
            json=event.payload,
            timeout=5
        )

        latency_ms = int((time.time() - start) * 1000)
        latency_sec = latency_ms / 1000

        success = response.status_code < 400

        delivery = models.Delivery(
            event_id=event.id,
            webhook_id=webhook.id,
            status="success" if success else "failed",
            response_code=response.status_code,
            latency_ms=latency_ms
        )

        db.add(delivery)
        db.commit()

        logger.info(
            "delivery_result",
            extra={
                "service": "worker",
                "request_id": request_id,
                "event_id": event.id,
                "webhook_url": webhook.url,
                "status_code": response.status_code,
                "latency": latency_ms,
            }
        )
        if success:
            DELIVERY_SUCCESS.inc()
            DELIVERY_LATENCY.observe(latency_sec)
        else:
            DELIVERY_FAILURE.inc()
        return success
    except Exception as e:
        logger.error(
            "delivery_error",
            extra={
                "service": "worker",
                "request_id": request_id,
                "event_id": event.id,
                "webhook_url": webhook.url,
                "error": str(e)
            }
        )
        DELIVERY_FAILURE.inc()
        delivery = models.Delivery(
            event_id=event.id,
            webhook_id=webhook.id,
            status="failed",
            response_code=None,
            latency_ms=None
        )
        db.add(delivery)
        db.commit()
        return False
    
if __name__ == "__main__":
    consume()