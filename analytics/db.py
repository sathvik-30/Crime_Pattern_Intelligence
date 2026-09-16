"""
Shared database connection helper for every module under /analytics.

Centralizing this here (rather than duplicating a create_engine() call in
each module) means the connection string is built in exactly one place,
and every module picks up credentials the same way: from environment
variables loaded out of a .env file via python-dotenv, never hardcoded.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Resolve .env relative to the project root (one level up from this file),
# not the current working directory, so `python analytics/heatmap.py`
# finds it regardless of where it's invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def get_engine() -> Engine:
    """Builds a SQLAlchemy engine for the crime_pattern_intelligence DB.

    Uses the psycopg2 driver explicitly (postgresql+psycopg2://...) --
    SQLAlchemy's default Postgres dialect -- rather than leaving the
    driver unspecified, so the dependency it requires (psycopg2-binary)
    is obvious from the connection string itself.
    """
    host = os.environ.get("CPI_DB_HOST", "localhost")
    port = os.environ.get("CPI_DB_PORT", "5432")
    name = os.environ.get("CPI_DB_NAME", "crime_pattern_intelligence")
    user = os.environ.get("CPI_DB_USER", "cpi_user")
    password = os.environ.get("CPI_DB_PASSWORD", "cpi_password")

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    return create_engine(url)


def ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR
