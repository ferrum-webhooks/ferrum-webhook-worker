import logging
import sys
from pythonjsonlogger import jsonlogger

from app.tracing import TraceLogFilter


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)

    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(event_id)s %(trace_id)s"
    )

    handler.addFilter(TraceLogFilter())
    handler.setFormatter(formatter)
    logger.handlers = [handler]