"""
A simple regression estimating which area/shift needs additional patrol
coverage next month, plus a supporting officer resolution-rate
leaderboard (staffing decisions need to know who's actually closing
cases, not just where crime is happening).

Runnable standalone:
    python analytics/resource_allocation.py

Saves analytics/output/patrol_recommendations.csv and
analytics/output/officer_resolution_leaderboard.csv, and prints both for
quick verification.
"""

import sys
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

try:
    from analytics.db import ensure_output_dir, get_engine
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from db import ensure_output_dir, get_engine

# Three 8-hour shifts. Bucketing by hour-of-day rather than using
# crime_reports.date_reported (which lags the actual incident) keeps this
# aligned with when the crime actually happened.
SHIFT_CASE_SQL = """
    CASE
        WHEN EXTRACT(HOUR FROM date_occurred) BETWEEN 0 AND 7 THEN 'Night'
        WHEN EXTRACT(HOUR FROM date_occurred) BETWEEN 8 AND 15 THEN 'Day'
        ELSE 'Evening'
    END
"""


def load_area_shift_monthly(engine) -> pd.DataFrame:
    query = f"""
        SELECT
            area,
            {SHIFT_CASE_SQL} AS shift,
            DATE_TRUNC('month', date_occurred)::date AS month,
            COUNT(*) AS crime_count
        FROM crime_reports
        GROUP BY area, shift, DATE_TRUNC('month', date_occurred)::date
        ORDER BY area, shift, month
    """
    return pd.read_sql(query, engine, parse_dates=["month"])


def load_officer_counts_by_area(engine) -> pd.DataFrame:
    query = """
        SELECT ps.jurisdiction_area AS area, COUNT(o.officer_id) AS officer_count
        FROM police_stations ps
        LEFT JOIN officers o ON o.station_id = ps.station_id
        GROUP BY ps.jurisdiction_area
    """
    return pd.read_sql(query, engine)


def officer_resolution_leaderboard(engine, min_cases: int = 10) -> pd.DataFrame:
    """Historical case-resolution performance per officer.

    min_cases filters out officers with too few assigned cases for a
    resolution rate to be statistically meaningful -- an officer who
    happened to close 2 of 2 small cases isn't a "100% performer" in any
    useful sense, just a small sample the leaderboard shouldn't be
    dominated by.
    """
    query = """
        SELECT
            o.officer_id,
            o.name AS officer_name,
            o.rank,
            ps.jurisdiction_area AS area,
            COUNT(c.case_id) AS total_cases,
            COUNT(c.case_id) FILTER (WHERE c.case_status = 'Closed') AS closed_cases
        FROM officers o
        JOIN police_stations ps ON ps.station_id = o.station_id
        JOIN cases c ON c.assigned_officer_id = o.officer_id
        GROUP BY o.officer_id, o.name, o.rank, ps.jurisdiction_area
        HAVING COUNT(c.case_id) >= %(min_cases)s
    """
    df = pd.read_sql(query, engine, params={"min_cases": min_cases})
    df["resolution_rate"] = (df["closed_cases"] / df["total_cases"]).round(3)
    return df.sort_values("resolution_rate", ascending=False).reset_index(drop=True)


def build_features(monthly: pd.DataFrame) -> pd.DataFrame:
    """Adds a per-(area, shift) month index (0, 1, 2, ...): the
    regression's time-trend feature. Each area/shift group needs its own
    0-based index into its own timeline, not a shared calendar date,
    since the model treats "3 months into this group's history" as the
    trend signal.
    """
    df = monthly.copy()
    df["month_index"] = (
        df.groupby(["area", "shift"])["month"].rank(method="first").astype(int) - 1
    )
    return df


def train_model(features: pd.DataFrame) -> Pipeline:
    """crime_count ~ area + shift + month_index, via one-hot encoding
    plus linear regression.

    WHY linear regression over a heavier model: the task calls for a
    "simple predictive model," and with only 24 monthly observations per
    area/shift group there isn't enough history to responsibly fit
    something like gradient boosting without overfitting noise. One-hot
    encoding area and shift lets one linear model learn a separate
    baseline level per area/shift combination while sharing a single
    time-trend coefficient across all of them.
    """
    preprocessor = ColumnTransformer(
        transformers=[("cat", OneHotEncoder(handle_unknown="ignore"), ["area", "shift"])],
        remainder="passthrough",
    )
    pipeline = Pipeline([
        ("preprocess", preprocessor),
        ("regressor", LinearRegression()),
    ])
    pipeline.fit(features[["area", "shift", "month_index"]], features["crime_count"])
    return pipeline


def predict_next_month(pipeline: Pipeline, features: pd.DataFrame) -> pd.DataFrame:
    """Predicts next month's crime_count for every (area, shift)
    combination, using next_month_index = that group's last observed
    index + 1."""
    next_index = features.groupby(["area", "shift"])["month_index"].max().reset_index()
    next_index["month_index"] = next_index["month_index"] + 1

    predicted = pipeline.predict(next_index[["area", "shift", "month_index"]])
    next_index["predicted_crime_count"] = predicted.clip(min=0).round(1)
    return next_index[["area", "shift", "predicted_crime_count"]]


def flag_understaffed(
    predicted: pd.DataFrame, officer_counts: pd.DataFrame, top_n: int = 10
) -> pd.DataFrame:
    """Ranks area/shift combinations by predicted crimes per officer --
    where the same headcount will be covering the most predicted crime
    next month.

    WHY divide an area's officer_count by 3: officers aren't tagged with
    a shift in this schema (there's no shift column on officers), so an
    area's total headcount is split evenly across its 3 shifts as a
    simple stand-in for "how many are typically on duty at once." A real
    deployment system would track actual shift rosters instead.
    """
    merged = predicted.merge(officer_counts, on="area", how="left")
    merged["officers_on_shift"] = (merged["officer_count"] / 3).round(1)
    merged["predicted_crimes_per_officer"] = (
        merged["predicted_crime_count"] / merged["officers_on_shift"].replace(0, pd.NA)
    ).round(2)

    return (
        merged.sort_values("predicted_crimes_per_officer", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )


def main():
    engine = get_engine()

    monthly = load_area_shift_monthly(engine)
    officer_counts = load_officer_counts_by_area(engine)

    features = build_features(monthly)
    model = train_model(features)
    predicted = predict_next_month(model, features)
    recommendations = flag_understaffed(predicted, officer_counts)

    out_dir = ensure_output_dir()
    rec_path = out_dir / "patrol_recommendations.csv"
    recommendations.to_csv(rec_path, index=False)

    leaderboard = officer_resolution_leaderboard(engine)
    leaderboard_path = out_dir / "officer_resolution_leaderboard.csv"
    leaderboard.to_csv(leaderboard_path, index=False)

    print("Top area/shift combinations recommended for additional patrol coverage:")
    print(recommendations.to_string(index=False))
    print(f"\nRecommendations saved to: {rec_path}")

    print("\nOfficer resolution-rate leaderboard (top 10, min 10 cases assigned):")
    print(leaderboard.head(10).to_string(index=False))
    print(f"Leaderboard saved to: {leaderboard_path}")


if __name__ == "__main__":
    main()
