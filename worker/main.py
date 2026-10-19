# file: worker/main.py
#
# Entry point. Threads: consumer (stream -> deliveries), outbox relay (Postgres -> stream),
# retry scheduler (due retries -> outbox), health/metrics server.
#
# Graceful shutdown: SIGTERM sets `shutdown`; every loop finishes its current unit of work and
# exits; the consumer finishes (and acks) in-flight deliveries first. No new work is claimed.

import logging
import signal
import threading

from dotenv import load_dotenv

load_dotenv()

from app.db import dispose_engine, get_session_local  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402
from app.tracing import setup_tracing  # noqa: E402
from worker import config  # noqa: E402
from worker.consumer import consume_loop  # noqa: E402
from worker.health import Health, start_server  # noqa: E402
from worker.relay import purge_published, relay_once  # noqa: E402
from worker.scheduler import recover_orphaned, recover_stale_pending, schedule_due_retries  # noqa: E402

setup_tracing("ferrum-worker")
setup_logging()
logger = logging.getLogger(__name__)

shutdown_event = threading.Event()


def handle_shutdown(signum, frame):
    logger.warning("shutdown_signal_received", extra={"service": "worker", "signal": signum})
    shutdown_event.set()


def _periodic(name, fn, interval, shutdown, heartbeat):
    while not shutdown.is_set():
        heartbeat()
        try:
            fn()
        except Exception as e:
            logger.error(f"{name}_error", extra={"service": "worker", "error": str(e)})
            shutdown.wait(1)
        shutdown.wait(interval)


def run(shutdown: threading.Event = shutdown_event):
    session_factory = get_session_local()
    r = config.make_redis()
    health = Health(session_factory, r, shutdown)
    server = start_server(health)

    def relay_tick():
        # drain fully before sleeping so bursts don't wait a poll interval per batch
        while not shutdown.is_set() and relay_once(session_factory, r) >= config.RELAY_BATCH:
            pass

    last_purge = {"t": 0.0}

    def sweep_tick():
        import time
        schedule_due_retries(session_factory)
        recover_orphaned(session_factory)
        recover_stale_pending(session_factory)
        if time.monotonic() - last_purge["t"] > 300:
            last_purge["t"] = time.monotonic()
            purge_published(session_factory)

    threads = [
        threading.Thread(target=_periodic, name="relay", daemon=True,
                         args=("relay", relay_tick, config.RELAY_INTERVAL_SECONDS, shutdown,
                               health.beater("relay"))),
        threading.Thread(target=_periodic, name="scheduler", daemon=True,
                         args=("scheduler", sweep_tick, config.SCHEDULER_INTERVAL_SECONDS, shutdown,
                               health.beater("scheduler"))),
    ]
    for t in threads:
        t.start()

    try:
        consume_loop(session_factory, r, shutdown, health.beater("consumer"))
    finally:
        shutdown.set()
        for t in threads:
            t.join(timeout=10)
        server.shutdown()
        r.close()
        dispose_engine()
        logger.warning("worker_shutdown_complete", extra={"service": "worker"})


def main():
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    run()


if __name__ == "__main__":
    main()
