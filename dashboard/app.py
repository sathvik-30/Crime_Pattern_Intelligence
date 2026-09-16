"""
Overview page (Phase 5, page 1 of 5): KPI cards + a crime trend line chart.

Run the whole multipage app with:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Make dashboard/ importable regardless of how Streamlit executed this
# file (as the app's main script vs. a page navigated to directly) --
# searches upward for the directory containing common.py rather than
# assuming a fixed number of parent directories, the same pattern
# common.py itself uses to find the project root.
_here = Path(__file__).resolve()
for _candidate in [_here.parent, *_here.parents]:
    if (_candidate / "common.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from common import date_range_filter, get_areas, get_crime_types, get_engine

from analytics.db import crime_report_filters
from analytics.time_series import load_monthly_counts

st.set_page_config(page_title="Overview | Crime Pattern Intelligence", layout="wide")


@st.cache_data(ttl=300)
def load_kpis(_engine, date_from, date_to, crime_types, areas) -> dict:
    """One aggregate query for all four KPI cards, filtered by the same
    date/crime-type/area predicates as everything else on this page (via
    the shared analytics.db.crime_report_filters, so the date_to
    end-of-day handling stays identical everywhere it's used) -- joins
    cases to crime_reports since date/crime_type/area live on the report,
    not the case.
    """
    extra_clause, params = crime_report_filters(
        date_from, date_to, crime_types, areas, date_column="cr.date_occurred"
    )
    query = f"""
        SELECT
            COUNT(*) AS total_cases,
            COUNT(*) FILTER (WHERE c.case_status = 'Closed') AS closed_cases,
            COUNT(*) FILTER (WHERE c.case_status <> 'Closed') AS active_cases,
            AVG(c.closed_date - c.opened_date) FILTER (WHERE c.case_status = 'Closed') AS avg_days_to_resolution
        FROM cases c
        JOIN crime_reports cr ON cr.report_id = c.report_id
        WHERE TRUE {extra_clause}
    """
    row = pd.read_sql(query, _engine, params=params).iloc[0]

    total = int(row["total_cases"])
    closed = int(row["closed_cases"])
    return {
        "total_cases": total,
        "resolution_rate_pct": round(100.0 * closed / total, 1) if total else 0.0,
        "active_cases": int(row["active_cases"]),
        "avg_days_to_resolution": (
            round(float(row["avg_days_to_resolution"]), 1)
            if pd.notna(row["avg_days_to_resolution"])
            else None
        ),
    }


def main():
    st.title("Overview")
    st.caption("Crime Pattern Intelligence System — city-wide KPIs and trend")

    engine = get_engine()
    crime_type_options = get_crime_types(engine)
    area_options = get_areas(engine)

    with st.expander("Filters", expanded=True):
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            date_from, date_to = date_range_filter(engine, key_prefix="overview")
        with col2:
            selected_crime_types = st.multiselect(
                "Crime type", options=crime_type_options, default=[], key="overview_crime_types"
            )
        with col3:
            selected_areas = st.multiselect(
                "Area", options=area_options, default=[], key="overview_areas"
            )

    kpis = load_kpis(engine, date_from, date_to, selected_crime_types, selected_areas)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Cases", f"{kpis['total_cases']:,}")
    col2.metric("Resolution Rate", f"{kpis['resolution_rate_pct']}%")
    col3.metric("Active Cases", f"{kpis['active_cases']:,}")
    col4.metric(
        "Avg. Time to Resolution",
        f"{kpis['avg_days_to_resolution']} days" if kpis["avg_days_to_resolution"] is not None else "N/A",
    )

    st.subheader("Crime Trend")
    monthly = load_monthly_counts(engine, crime_types=selected_crime_types or None, areas=selected_areas or None)

    if monthly.empty:
        st.info("No crime reports match the current filters.")
    else:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(x=monthly.index, y=monthly["crime_count"], mode="lines+markers", name="Crime reports")
        )
        fig.update_layout(xaxis_title="Month", yaxis_title="Crime reports", height=420)
        st.plotly_chart(fig, width="stretch")


main()
