"""
Monthly/weekly crime trend analysis, seasonal decomposition, and a
next-month volume forecast.

Runnable standalone:
    python analytics/time_series.py

Saves an interactive Plotly chart (actual vs. trend vs. forecast) to
analytics/output/time_series_forecast.html and prints the numbers behind
it for quick verification.
"""

import sys
import warnings
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.seasonal import seasonal_decompose

try:
    from analytics.db import ensure_output_dir, get_engine
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from db import ensure_output_dir, get_engine


def load_monthly_counts(engine) -> pd.DataFrame:
    query = """
        SELECT DATE_TRUNC('month', date_occurred)::date AS month, COUNT(*) AS crime_count
        FROM crime_reports
        GROUP BY DATE_TRUNC('month', date_occurred)::date
        ORDER BY month
    """
    df = pd.read_sql(query, engine, parse_dates=["month"])
    return df.set_index("month")


def load_weekly_counts(engine) -> pd.DataFrame:
    query = """
        SELECT DATE_TRUNC('week', date_occurred)::date AS week, COUNT(*) AS crime_count
        FROM crime_reports
        GROUP BY DATE_TRUNC('week', date_occurred)::date
        ORDER BY week
    """
    df = pd.read_sql(query, engine, parse_dates=["week"])
    return df.set_index("week")


def decompose_seasonal(monthly: pd.DataFrame, period: int = 12) -> pd.DataFrame:
    """Additive decomposition into trend / seasonal / residual components.

    WHY additive (not multiplicative): monthly counts here vary by tens
    of reports around the trend line, not by a multiplier that scales
    with the trend's own level -- additive is the right model when the
    seasonal swing's *size* stays roughly constant regardless of the
    overall volume at the time.

    WHY period=12 with only 24 monthly observations: seasonal_decompose
    needs at least 2 full cycles to estimate a seasonal component at all;
    24 months is exactly 2 years, the minimum that makes a 12-month
    seasonal period estimable rather than an error.
    """
    series = monthly["crime_count"].asfreq("MS")
    # Postgres DATE_TRUNC never skips a month for this dataset, but
    # asfreq() would introduce a NaN if it ever did -- fill defensively
    # rather than let decomposition silently propagate a gap.
    series = series.fillna(0)

    result = seasonal_decompose(series, model="additive", period=period)
    return pd.DataFrame(
        {
            "observed": result.observed,
            "trend": result.trend,
            "seasonal": result.seasonal,
            "residual": result.resid,
        }
    )


def forecast_next_month(monthly: pd.DataFrame) -> dict:
    """A one-step-ahead forecast of next month's crime volume.

    WHY ARIMA over Prophet (the task's other allowed option): Prophet
    depends on a separate Stan/C++ backend (via cmdstanpy) that has to be
    compiled or downloaded per-platform, which is a heavy, fragile
    dependency for what the task calls a "simple forecast." ARIMA is
    pure numpy/scipy through statsmodels -- a library this module already
    depends on for seasonal_decompose -- so it adds no new dependency and
    nothing to compile.

    WHY order=(1,1,1) rather than a searched/optimal order: with only 24
    monthly observations, fitting a larger model (e.g. a seasonal
    SARIMAX) risks overfitting noise. (1,1,1) is the standard "simple
    baseline" ARIMA spec -- one autoregressive term, one differencing
    step to handle the trend, one moving-average term to absorb
    short-term shocks -- appropriate for a small, short series.
    """
    series = monthly["crime_count"].asfreq("MS").fillna(0)

    with warnings.catch_warnings():
        # statsmodels warns about the frequency/date index on a series
        # this short; the warning is about inference precision, not
        # correctness, and would otherwise clutter this module's output.
        warnings.simplefilter("ignore")
        model = ARIMA(series, order=(1, 1, 1))
        fitted = model.fit()
        forecast_result = fitted.get_forecast(steps=1)

    next_month = series.index[-1] + pd.DateOffset(months=1)
    predicted = float(forecast_result.predicted_mean.iloc[0])
    conf_int = forecast_result.conf_int(alpha=0.05).iloc[0]

    return {
        "month": next_month,
        "predicted_count": round(predicted, 1),
        "conf_int_low": round(float(conf_int.iloc[0]), 1),
        "conf_int_high": round(float(conf_int.iloc[1]), 1),
    }


def build_forecast_chart(monthly: pd.DataFrame, decomposition: pd.DataFrame, forecast: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=monthly.index, y=monthly["crime_count"],
                              mode="lines+markers", name="Actual"))
    fig.add_trace(go.Scatter(x=decomposition.index, y=decomposition["trend"],
                              mode="lines", name="Trend", line=dict(dash="dash")))
    fig.add_trace(go.Scatter(
        x=[monthly.index[-1], forecast["month"]],
        y=[monthly["crime_count"].iloc[-1], forecast["predicted_count"]],
        mode="lines+markers", name="Forecast", line=dict(color="firebrick"),
    ))
    fig.add_trace(go.Scatter(
        x=[forecast["month"], forecast["month"]],
        y=[forecast["conf_int_low"], forecast["conf_int_high"]],
        mode="lines", name="95% CI", line=dict(color="firebrick", dash="dot"),
    ))
    fig.update_layout(
        title="Monthly Crime Volume: Actual, Trend, and Next-Month Forecast",
        xaxis_title="Month", yaxis_title="Crime reports",
    )
    return fig


def main():
    engine = get_engine()
    monthly = load_monthly_counts(engine)
    weekly = load_weekly_counts(engine)

    decomposition = decompose_seasonal(monthly)
    forecast = forecast_next_month(monthly)

    fig = build_forecast_chart(monthly, decomposition, forecast)
    out_dir = ensure_output_dir()
    out_path = out_dir / "time_series_forecast.html"
    fig.write_html(str(out_path), include_plotlyjs="cdn")

    print(f"Loaded {len(monthly)} monthly buckets and {len(weekly)} weekly buckets.")
    print("\nLast 6 months of actual crime counts:")
    print(monthly.tail(6).to_string())

    print(
        "\nSeasonal decomposition (all 24 months -- note trend is NaN for the "
        "first/last 6 months: a period=12 centered moving average needs "
        "6 months on each side to compute, which is expected edge behavior, "
        "not missing data):"
    )
    print(decomposition.round(1).to_string())

    print(
        f"\nForecast for {forecast['month'].strftime('%Y-%m')}: "
        f"{forecast['predicted_count']} crimes "
        f"(95% CI: {forecast['conf_int_low']}-{forecast['conf_int_high']})"
    )
    print(f"Chart saved to: {out_path}")


if __name__ == "__main__":
    main()
