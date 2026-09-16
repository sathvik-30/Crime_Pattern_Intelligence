"""
Case Resolution page (Phase 5, page 4 of 5): a funnel from reported ->
under investigation -> reached court -> final verdict, filterable by
date range and crime type.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Make dashboard/ importable regardless of how Streamlit executed this
# file -- see dashboard/app.py's identical bootstrap for why this can't
# just assume a fixed number of parent directories.
_here = Path(__file__).resolve()
for _candidate in [_here.parent, *_here.parents]:
    if (_candidate / "common.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from common import date_range_filter, get_crime_types, get_engine

from analytics.db import crime_report_filters

st.set_page_config(page_title="Case Resolution | Crime Pattern Intelligence", layout="wide")


@st.cache_data(ttl=300)
def load_funnel_counts(_engine, date_from, date_to, crime_types) -> dict:
    """Four counts, each a strict subset of the one before it, forming
    the pipeline stage by stage:

      1. Reported     -- every crime_report in the filtered window.
      2. Investigation -- reports that became a case at all (a report
         marked Unfounded never gets one -- see cases.report_id's UNIQUE
         FK and migration 006's comment).
      3. Reached court -- those cases with at least one court_status row.
      4. Verdict       -- those with a *final* verdict (excludes a
         court_status row still sitting at 'Pending').

    One query per stage (rather than one query with four FILTERed
    subqueries) because each stage's condition reaches through a
    different join depth (crime_reports -> cases -> court_status), and
    keeping them separate makes each stage's SQL a direct, ready-to-run
    answer to "how many cases are at stage N."
    """
    extra_clause, params = crime_report_filters(
        date_from, date_to, crime_types, date_column="cr.date_occurred"
    )

    reported = pd.read_sql(
        f"SELECT COUNT(*) AS n FROM crime_reports cr WHERE TRUE {extra_clause}", _engine, params=params
    ).iloc[0]["n"]

    investigation = pd.read_sql(
        f"""
        SELECT COUNT(*) AS n
        FROM cases c
        JOIN crime_reports cr ON cr.report_id = c.report_id
        WHERE TRUE {extra_clause}
        """,
        _engine, params=params,
    ).iloc[0]["n"]

    reached_court = pd.read_sql(
        f"""
        SELECT COUNT(DISTINCT c.case_id) AS n
        FROM cases c
        JOIN crime_reports cr ON cr.report_id = c.report_id
        JOIN court_status cs ON cs.case_id = c.case_id
        WHERE TRUE {extra_clause}
        """,
        _engine, params=params,
    ).iloc[0]["n"]

    verdict = pd.read_sql(
        f"""
        SELECT COUNT(DISTINCT c.case_id) AS n
        FROM cases c
        JOIN crime_reports cr ON cr.report_id = c.report_id
        JOIN court_status cs ON cs.case_id = c.case_id
        WHERE TRUE {extra_clause}
          AND cs.verdict IS NOT NULL AND cs.verdict <> 'Pending'
        """,
        _engine, params=params,
    ).iloc[0]["n"]

    return {
        "Reported": int(reported),
        "Under Investigation": int(investigation),
        "Reached Court": int(reached_court),
        "Final Verdict": int(verdict),
    }


def main():
    st.title("Case Resolution")
    st.caption("Pipeline from a filed report through to a final court verdict")

    engine = get_engine()
    crime_type_options = get_crime_types(engine)

    with st.expander("Filters", expanded=True):
        col1, col2 = st.columns([2, 2])
        with col1:
            date_from, date_to = date_range_filter(engine, key_prefix="funnel")
        with col2:
            selected_crime_types = st.multiselect(
                "Crime type", options=crime_type_options, default=[], key="funnel_crime_types"
            )

    counts = load_funnel_counts(engine, date_from, date_to, selected_crime_types)
    stages = list(counts.keys())
    values = list(counts.values())

    fig = go.Figure(
        go.Funnel(
            y=stages,
            x=values,
            textposition="inside",
            textinfo="value+percent initial",
        )
    )
    fig.update_layout(height=480)
    st.plotly_chart(fig, width="stretch")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Reported", f"{values[0]:,}")
    col2.metric("Under Investigation", f"{values[1]:,}")
    col3.metric("Reached Court", f"{values[2]:,}")
    col4.metric("Final Verdict", f"{values[3]:,}")

    if values[0]:
        st.caption(
            f"{round(100 * values[1] / values[0], 1)}% of reports became a case, "
            f"{round(100 * values[3] / values[0], 1)}% of all reports ended in a final verdict."
        )


main()
