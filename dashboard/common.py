"""
Shared setup for every dashboard page: making /analytics importable,
a cached engine, and the small lookup queries (distinct crime types,
areas, date bounds) every filter widget needs to populate its options.

Every page in dashboard/app.py and dashboard/pages/*.py imports from here
first, so the sys.path fix and the cached engine only exist in one place.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# Walk up from this file until we find the project root (marked by
# requirements.txt), then add it to sys.path so `import analytics` works
# regardless of whether Streamlit runs this as the main script or as a
# page under dashboard/pages/ -- those get different working directories
# and different automatic sys.path entries.
_here = Path(__file__).resolve()
for _candidate in [_here.parent, *_here.parents]:
    if (_candidate / "requirements.txt").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from analytics.db import get_engine as _get_engine  # noqa: E402


@st.cache_resource
def get_engine():
    """One SQLAlchemy engine per Streamlit session, not one per query --
    st.cache_resource is Streamlit's construct for caching a live
    resource/connection object, as opposed to st.cache_data, which is for
    cacheable return *values* like DataFrames."""
    return _get_engine()


@st.cache_data(ttl=600)
def get_crime_types(_engine) -> list:
    df = pd.read_sql("SELECT DISTINCT crime_type FROM crime_reports ORDER BY crime_type", _engine)
    return df["crime_type"].tolist()


@st.cache_data(ttl=600)
def get_areas(_engine) -> list:
    df = pd.read_sql("SELECT DISTINCT area FROM crime_reports ORDER BY area", _engine)
    return df["area"].tolist()


@st.cache_data(ttl=600)
def get_date_bounds(_engine) -> tuple:
    df = pd.read_sql(
        "SELECT MIN(date_occurred)::date AS min_date, MAX(date_occurred)::date AS max_date FROM crime_reports",
        _engine,
    )
    return df.iloc[0]["min_date"], df.iloc[0]["max_date"]


def date_range_filter(engine, key_prefix: str):
    """Renders a date-range picker defaulted to the full seeded range and
    returns (date_from, date_to). Centralized so every page's date filter
    looks and behaves the same way."""
    min_date, max_date = get_date_bounds(engine)
    default_from = min_date if isinstance(min_date, date) else min_date.date()
    default_to = max_date if isinstance(max_date, date) else max_date.date()

    picked = st.date_input(
        "Date range",
        value=(default_from, default_to),
        min_value=default_from,
        max_value=default_to,
        key=f"{key_prefix}_date_range",
    )
    if isinstance(picked, tuple) and len(picked) == 2:
        return picked
    # A user can leave a single date selected mid-pick; fall back to the
    # full range rather than passing a half-formed filter to a query.
    return default_from, default_to
