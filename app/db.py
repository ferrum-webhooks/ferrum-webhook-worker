# file: app/db.py

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import OperationalError
import time
import os

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', 5432)
DB_USER = os.getenv('DB_USER', 'webhook_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'webhook_pass')
DB_NAME = os.getenv('DB_NAME', 'webhook_db')

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

MAX_RETRIES = 10
RETRY_DELAY = 2  # seconds

def create_db_engine():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            engine = create_engine(DATABASE_URL,
                                   pool_size=5,
                                   max_overflow=10,
                                   pool_pre_ping=True)
            # Test connection
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("Database connection established")
            return engine
        except OperationalError as e:
            print(f"Database connection failed (attempt {attempt}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES:
                raise RuntimeError("Could not connect to the database after multiple attempts")
            time.sleep(RETRY_DELAY)

engine = create_db_engine()
SessionLocal = sessionmaker(autoflush=False, autocommit=False, bind=engine)
Base = declarative_base()