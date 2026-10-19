# file: app/db.py

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from dotenv import load_dotenv
import logging
import time
import os

from app.tracing import instrument_engine

load_dotenv()

logger = logging.getLogger(__name__)

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', 5432)
DB_USER = os.getenv('DB_USER', 'webhook_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'webhook_pass')
DB_NAME = os.getenv('DB_NAME', 'webhook_db')

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

MAX_RETRIES = 10
RETRY_DELAY = 2  # seconds

Base = declarative_base()

_engine = None
_session_factory = None


def create_db_engine():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            engine = create_engine(DATABASE_URL,
                                   pool_size=int(os.getenv("DB_POOL_SIZE", 10)),
                                   max_overflow=10,
                                   pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("database_connected")
            return engine
        except OperationalError as e:
            logger.warning("database_connect_failed",
                           extra={"attempt": attempt, "max": MAX_RETRIES, "error": str(e)})
            if attempt == MAX_RETRIES:
                raise RuntimeError("Could not connect to the database after multiple attempts")
            time.sleep(RETRY_DELAY)


def get_engine():
    """Lazy: importing this module must not open a DB connection."""
    global _engine
    if _engine is not None:
        return _engine
    if os.getenv('TESTING') == 'true' and os.getenv('TEST_DATABASE_URL'):
        # Run the suite against a real (disposable!) Postgres: SKIP LOCKED, row locks, real concurrency.
        _engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_size=20, max_overflow=20, pool_pre_ping=True)
        return _engine
    if os.getenv('TESTING') == 'true':
        _engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                poolclass=StaticPool)
        return _engine
    _engine = create_db_engine()
    instrument_engine(_engine)
    return _engine


def get_session_local():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(autoflush=False, autocommit=False, bind=get_engine())
    return _session_factory


def dispose_engine():
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine, _session_factory = None, None
