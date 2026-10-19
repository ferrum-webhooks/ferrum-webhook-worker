# file: worker/signing.py
#
# Standard Webhooks signing (https://www.standardwebhooks.com/):
#   webhook-id         stable message id (same value on every retry => receivers can dedupe)
#   webhook-timestamp  unix seconds, refreshed on every attempt (replay protection)
#   webhook-signature  "v1," + base64(HMAC-SHA256(key, f"{id}.{timestamp}.{body}"))
# The key is the base64-decoded part of the "whsec_..." secret.

import base64
import hashlib
import hmac
import time
from typing import Optional

SECRET_PREFIX = "whsec_"
DEFAULT_TOLERANCE_SECONDS = 300


def _key(secret: str) -> bytes:
    if secret.startswith(SECRET_PREFIX):
        secret = secret[len(SECRET_PREFIX):]
    return base64.b64decode(secret)


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    signed = f"{msg_id}.{timestamp}.".encode() + body
    digest = hmac.new(_key(secret), signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def webhook_headers(secret: str, msg_id: str, body: bytes, timestamp: Optional[int] = None) -> dict:
    ts = int(time.time()) if timestamp is None else timestamp
    return {
        "webhook-id": msg_id,
        "webhook-timestamp": str(ts),
        "webhook-signature": sign(secret, msg_id, ts, body),
    }


def verify(secret: str, headers: dict, body: bytes,
           tolerance: int = DEFAULT_TOLERANCE_SECONDS, now: Optional[float] = None) -> bool:
    """Reference verifier (what a receiver should do). Accepts any space-separated v1 signature."""
    try:
        msg_id = headers["webhook-id"]
        ts = int(headers["webhook-timestamp"])
        candidates = headers["webhook-signature"].split(" ")
    except (KeyError, ValueError):
        return False
    if abs((time.time() if now is None else now) - ts) > tolerance:
        return False
    expected = sign(secret, msg_id, ts, body)
    return any(hmac.compare_digest(expected, c) for c in candidates)
