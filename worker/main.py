# file: worker/main.py

import json
import time
import redis
import requests
import logging

from app.db import SessionLocal
from app import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_client = redis.Redis(
    host="localhost",
    port=6379,
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

            logger.info(f"Received event: {event_data}")

            process_event(event_data)

        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            time.sleep(1)

def process_event(event_data: dict):
    db = get_db()

    try:
        event_id = event_data["event_id"]

        # Fetch event
        event = db.query(models.Event).filter(models.Event.id == event_id).first()

        if not event:
            logger.error(f"Event not found: {event_id}")
            return
        
        event.status = "processing"
        db.commit()

        # Fetch matching webhooks
        webhooks = db.query(models.Webhook).filter(
            models.Webhook.event_type == event.event_type
        ).all()

        logger.info(f"Found {len(webhooks)} webhooks")

        all_success = True

        for webhook in webhooks:
            success = deliver_event(db, event, webhook)
            if not success:
                all_success = False
        event.status = "delivered" if all_success else "failed"
        db.commit()
    except Exception as e:
        logger.error(f"Error processing event: {e}")
        event.status = "failed"
        db.commit()
    finally:
        db.close()

def deliver_event(db, event, webhook):
    try:
        start = time.time()

        response = requests.post(
            webhook.url,
            json=event.payload,
            timeout=5
        )

        latency = int((time.time() - start) * 1000)

        success = response.status_code < 400

        delivery = models.Delivery(
            event_id=event.id,
            webhook_id=webhook.id,
            status="success" if success else "failed",
            response_code=response.status_code,
            latency_ms=latency
        )

        db.add(delivery)
        db.commit()

        logger.info(f"Delivered to {webhook.url} [{response.status_code}]")
        return success
    except Exception as e:
        logger.error(f"Delivery failed: {webhook.url} - {e}")
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