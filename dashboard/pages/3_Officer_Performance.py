"""
Officer Performance page (Phase 5, page 3 of 5): the vw_officer_workload
view (db/sql_features/views.sql) and the RANK() OVER (...) monthly
resolution leaderboard (db/sql_features/window_functions.sql), reused
verbatim from the Phase 3 SQL layer rather than reimplemented here.
"""

import sys
from pathlib import Path

import pandas as pd
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

from common import get_areas, get_engine

st.set_page_config(page_title="Officer Performance | Crime Pattern Intelligence", layout="wide")


@st.cache_data(ttl=300)
def load_officer_workload(_engine, areas):
    """Queries the vw_officer_workload view created in Phase 3 --
    filtering here happens in Python against the already-small (one row
    per officer) result rather than the view definition, since a view
    can't take parameters; adding a WHERE clause on top of the view
    (`SELECT * FROM vw_officer_workload WHERE station_name = ANY(...)`)
    still pushes the filter down into one SQL statement rather than
    fetching everything and slicing client-side.
    """
    if areas:
        query = "SELECT * FROM vw_officer_workload WHERE station_name = ANY(%(areas)s) ORDER BY open_case_count DESC"
        return pd.read_sql(query, _engine, params={"areas": list(areas)})
    return pd.read_sql("SELECT * FROM vw_officer_workload ORDER BY open_case_count DESC", _engine)


@st.cache_data(ttl=300)
def load_monthly_rankings(_engine) -> pd.DataFrame:
    """The exact RANK() OVER (PARTITION BY month ORDER BY cases_resolved
    DESC) query from db/sql_features/window_functions.sql -- see that
    file for the full rationale (RANK vs ROW_NUMBER/DENSE_RANK, why the
    CTE runs first)."""
    query = """
        WITH monthly_resolutions AS (
            SELECT
                assigned_officer_id,
                DATE_TRUNC('month', closed_date)::date AS month,
                COUNT(*)                               AS cases_resolved
            FROM cases
            WHERE case_status = 'Closed'
            GROUP BY assigned_officer_id, DATE_TRUNC('month', closed_date)::date
        )
        SELECT
            o.officer_id,
            o.name AS officer_name,
            mr.month,
            mr.cases_resolved,
            RANK() OVER (PARTITION BY mr.month ORDER BY mr.cases_resolved DESC) AS rank_in_month
        FROM monthly_resolutions mr
        JOIN officers o ON o.officer_id = mr.assigned_officer_id
        ORDER BY mr.month, rank_in_month, officer_name
    """
    return pd.read_sql(query, _engine, parse_dates=["month"])


def main():
    st.title("Officer Performance")
    st.caption("Workload (vw_officer_workload) and monthly resolution rankings (window functions)")

    engine = get_engine()

    tab_workload, tab_ranking = st.tabs(["Workload", "Monthly Resolution Ranking"])

    with tab_workload:
        area_options = get_areas(engine)
        selected_areas = st.multiselect(
            "Station area", options=area_options, default=[], key="officer_areas"
        )
        workload = load_officer_workload(engine, selected_areas)

        col1, col2 = st.columns(2)
        col1.metric("Officers shown", len(workload))
        col2.metric("Total open cases", int(workload["open_case_count"].sum()) if not workload.empty else 0)

        st.dataframe(
            workload.sort_values("open_case_count", ascending=False),
            hide_index=True,
            width="stretch",
        )

    with tab_ranking:
        rankings = load_monthly_rankings(engine)
        if rankings.empty:
            st.info("No closed cases yet.")
        else:
            months = sorted(rankings["month"].dt.strftime("%Y-%m").unique(), reverse=True)
            selected_month = st.selectbox("Month", options=months, key="officer_month")

            month_df = rankings[rankings["month"].dt.strftime("%Y-%m") == selected_month]
            month_df = month_df.sort_values("rank_in_month")

            st.dataframe(
                month_df[["rank_in_month", "officer_name", "cases_resolved"]],
                hide_index=True,
                width="stretch",
            )

            st.subheader("Top performers across the full history")
            totals = (
                rankings.groupby(["officer_id", "officer_name"])["cases_resolved"]
                .sum()
                .sort_values(ascending=False)
                .head(10)
                .reset_index()
            )
            st.bar_chart(totals.set_index("officer_name")["cases_resolved"])


main()
