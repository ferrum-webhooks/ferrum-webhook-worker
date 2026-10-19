import os

os.environ["TESTING"] = "true"
os.environ["ALLOW_PRIVATE_WEBHOOK_TARGETS"] = "true"   # tests use example.com / localhost targets

import pytest


def _guard_test_database():
    """create_all/drop_all run against TEST_DATABASE_URL on every test: refuse anything not obviously disposable."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url and "test" not in url.rsplit("/", 1)[-1].lower():
        raise RuntimeError("TEST_DATABASE_URL must point at a disposable database whose name contains 'test'")


_guard_test_database()
import redis

from app import db as app_db, models
from worker import config


def _redis():
    r = redis.Redis(decode_responses=True, socket_connect_timeout=0.3)
    try:
        r.ping()
    except Exception:
        pytest.skip("needs a local redis on :6379")
    return r


@pytest.fixture()
def r(monkeypatch):
    """Real Redis, isolated stream names per test run."""
    monkeypatch.setattr(config, "STREAM", "test:deliveries:stream")
    monkeypatch.setattr(config, "GROUP", "test-workers")
    monkeypatch.setattr(config, "DLQ_STREAM", "test:deliveries:dlq")
    client = _redis()
    for k in (config.STREAM, config.DLQ_STREAM):
        client.delete(k)
    yield client
    for k in (config.STREAM, config.DLQ_STREAM):
        client.delete(k)


@pytest.fixture()
def sf():
    engine = app_db.get_engine()
    app_db.Base.metadata.drop_all(engine)
    app_db.Base.metadata.create_all(engine)
    return app_db.get_session_local()


@pytest.fixture()
def seed(sf):
    """One user, one webhook, one event, one pending delivery + its outbox row."""
    db = sf()
    u = models.User(email="u@example.com", password_hash="x")
    db.add(u); db.flush()
    wh = models.Webhook(user_id=u.id, url="https://example.com/hook", event_type="t",
                        secret="whsec_" + "MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
    ev = models.Event(public_id="evt_abc", user_id=u.id, payload={"n": 1}, event_type="t")
    db.add_all([wh, ev]); db.flush()
    d = models.Delivery(event_id=ev.id, webhook_id=wh.id, status="pending", retries=0)
    db.add(d); db.flush()
    db.add(models.Outbox(delivery_id=d.id, request_id="req-1"))
    db.commit()
    ids = {"delivery": d.id, "event": ev.id, "webhook": wh.id}
    db.close()
    return ids


class FakeHTTP:
    def __init__(self, *codes):
        self.codes, self.calls = list(codes), []

    def post(self, url, data=None, headers=None, **kw):
        self.calls.append({"url": url, "data": data, "headers": headers, **kw})
        code = self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]
        if isinstance(code, Exception):
            raise code
        return type("Resp", (), {"status_code": code})()
