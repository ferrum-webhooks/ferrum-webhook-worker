# file: worker/health.py
#
# Tiny HTTP server on one port: /metrics (Prometheus), /healthz (liveness), /readyz (readiness).
#   liveness  = every background loop (consumer, relay, scheduler) has beaten recently.
#               A wedged consumer thread now gets the pod restarted; /metrics alone proved nothing.
#   readiness = Postgres and Redis reachable and we are not shutting down.

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from worker import config

logger = logging.getLogger(__name__)


class Health:
    def __init__(self, session_factory, redis_client, shutdown: threading.Event):
        self.session_factory = session_factory
        self.redis = redis_client
        self.shutdown = shutdown
        self._beats = {}

    def beat(self, name: str):
        self._beats[name] = time.monotonic()

    def beater(self, name: str):
        self.beat(name)
        return lambda: self.beat(name)

    def live(self):
        now = time.monotonic()
        stale = [n for n, t in self._beats.items() if now - t > config.HEALTH_STALE_SECONDS]
        return (not stale), {"stale_loops": stale}

    def ready(self):
        if self.shutdown.is_set():
            return False, {"reason": "shutting_down"}
        try:
            db = self.session_factory()
            try:
                db.execute(text("SELECT 1"))
            finally:
                db.close()
            self.redis.ping()
        except Exception as e:
            return False, {"reason": str(e)[:200]}
        return True, {}


def start_server(health: Health, port: int = config.HEALTH_PORT) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            import json
            if self.path == "/metrics":
                self._send(200, generate_latest(), CONTENT_TYPE_LATEST)
            elif self.path in ("/healthz", "/readyz"):
                ok, detail = health.live() if self.path == "/healthz" else health.ready()
                self._send(200 if ok else 503,
                           json.dumps({"status": "ok" if ok else "unavailable", **detail}).encode())
            else:
                self._send(404, b'{"error":"not found"}')

        def log_message(self, *args):   # probes every few seconds; keep logs quiet
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="health", daemon=True).start()
    logger.info("health_server_started", extra={"service": "worker", "port": port})
    return server
