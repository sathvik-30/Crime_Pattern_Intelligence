"""
Predictive page (Phase 5, page 5 of 5): the forecast chart from
analytics/time_series.py and the patrol allocation table from
analytics/resource_allocation.py, reused directly rather than
reimplemented.
"""

import sys
from pathlib import Path

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

from common import get_engine

from analytics.resource_allocation import (
    build_features,
    flag_understaffed,
    load_area_shift_monthly,
    load_officer_counts_by_area,
    officer_resolution_leaderboard,
    predict_next_month,
    train_model,
)
from analytics.time_series import (
    build_forecast_chart,
    decompose_seasonal,
    forecast_next_month,
    load_monthly_counts,
)

st.set_page_config(page_title="Predictive | Crime Pattern Intelligence", layout="wide")


@st.cache_data(ttl=600)
def compute_forecast(_engine):
    """No date/crime-type filters here on purpose: both the seasonal
    decomposition and the ARIMA forecast need the full, unbroken 24-month
    history to be valid at all (see time_series.py's docstrings) -- a
    filtered subset with gaps would silently produce a nonsense forecast
    rather than an error, so this page always shows the whole city's
    trend rather than exposing filters that could quietly break it.
    """
    monthly = load_monthly_counts(_engine)
    decomposition = decompose_seasonal(monthly)
    forecast = forecast_next_month(monthly)
    fig = build_forecast_chart(monthly, decomposition, forecast)
    return fig, forecast


@st.cache_data(ttl=600)
def compute_patrol_recommendations(_engine, top_n: int):
    monthly = load_area_shift_monthly(_engine)
    officer_counts = load_officer_counts_by_area(_engine)
    features = build_features(monthly)
    model = train_model(features)
    predicted = predict_next_month(model, features)
    return flag_understaffed(predicted, officer_counts, top_n=top_n)


@st.cache_data(ttl=600)
def compute_leaderboard(_engine, min_cases: int):
    return officer_resolution_leaderboard(_engine, min_cases=min_cases)


def main():
    st.title("Predictive")
    st.caption("Next-month crime forecast and recommended patrol allocation")

    engine = get_engine()

    st.subheader("City-wide Crime Forecast")
    fig, forecast = compute_forecast(engine)
    st.plotly_chart(fig, width="stretch")
    st.info(
        f"Forecast for **{forecast['month'].strftime('%Y-%m')}**: "
        f"**{forecast['predicted_count']}** crime reports "
        f"(95% CI: {forecast['conf_int_low']}–{forecast['conf_int_high']})"
    )

    st.subheader("Recommended Patrol Allocation")
    top_n = st.slider("How many area/shift combinations to show", min_value=5, max_value=20, value=10, key="patrol_top_n")
    recommendations = compute_patrol_recommendations(engine, top_n)
    st.dataframe(recommendations, hide_index=True, width="stretch")
    st.caption(
        "Ranked by predicted crimes per officer next month -- area/shift combinations near the "
        "top are where the same headcount will be covering the most predicted crime."
    )

    st.subheader("Officer Resolution-Rate Leaderboard")
    min_cases = st.slider("Minimum cases assigned", min_value=1, max_value=30, value=10, key="predictive_min_cases")
    leaderboard = compute_leaderboard(engine, min_cases)
    st.dataframe(leaderboard.head(15), hide_index=True, width="stretch")


main()
