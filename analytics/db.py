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


def crime_report_filters(date_from=None, date_to=None, crime_types=None, areas=None, date_column="date_occurred"):
    """Builds a parameterized SQL WHERE fragment + params dict for the
    common "filter crime_reports by date range / crime type / area"
    pattern shared by several analytics loaders and the Phase 5
    dashboard.

    WHY build this once here instead of in each caller: every filterable
    page in the dashboard (Overview, Geographic) needs the exact same
    three optional conditions applied to a query that already has its own
    WHERE clause (e.g. "location_lat IS NOT NULL") -- duplicating the
    None-check-then-append logic in each loader function would be a
    prime spot for one of them to drift out of sync with the others.

    Returns (clause, params): clause is "" if no filters are set, or
    " AND cond1 AND cond2 ..." (leading " AND ", ready to append after
    an existing WHERE ... condition) otherwise. Every condition uses a
    bound parameter (never raw string interpolation), even though these
    values come from Streamlit widgets and this app has no untrusted
    external input today -- building the habit of parameterizing is what
    keeps it safe if that ever changes.

    date_to's upper bound uses "< date_to + 1 day" rather than
    "<= date_to": date_column is a TIMESTAMP, but date_to (from a
    st.date_input) is a plain DATE. Comparing a timestamp <= a date casts
    the date to midnight of that day, which silently excludes every
    report on the end date itself except ones logged at exactly
    00:00:00 -- an easy-to-miss off-by-almost-a-day bug that would make
    "the full seeded date range" quietly drop the whole last day.
    """
    conditions = []
    params = {}

    if date_from is not None:
        conditions.append(f"{date_column} >= %(date_from)s")
        params["date_from"] = date_from
    if date_to is not None:
        conditions.append(f"{date_column} < %(date_to)s::date + INTERVAL '1 day'")
        params["date_to"] = date_to
    if crime_types:
        conditions.append("crime_type = ANY(%(crime_types)s)")
        params["crime_types"] = list(crime_types)
    if areas:
        conditions.append("area = ANY(%(areas)s)")
        params["areas"] = list(areas)

    clause = "".join(f" AND {c}" for c in conditions)
    return clause, params
