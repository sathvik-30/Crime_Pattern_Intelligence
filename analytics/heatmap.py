"""
Geographic density heatmap of crime_reports.

Runnable standalone:
    python analytics/heatmap.py

Saves an interactive HTML heatmap to analytics/output/crime_heatmap.html
and prints a density summary for quick verification without opening it.
"""

import sys
from pathlib import Path

import folium
import pandas as pd
from folium.plugins import HeatMap

try:
    from analytics.db import ensure_output_dir, get_engine
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from db import ensure_output_dir, get_engine

# Fictional city center from db/seed/generate_seed_data.py's CITY_CENTER,
# used only to center/zoom the map -- not a query filter.
CITY_CENTER = (41.4500, -87.6200)


def load_crime_locations(engine) -> pd.DataFrame:
    """One row per geocoded crime report. Rows with a NULL lat/lng
    (schema allows it -- see migration 005) are excluded since they
    can't be plotted."""
    query = """
        SELECT report_id, crime_type, area, severity, date_occurred,
               location_lat, location_lng
        FROM crime_reports
        WHERE location_lat IS NOT NULL AND location_lng IS NOT NULL
    """
    return pd.read_sql(query, engine)


def build_heatmap(df: pd.DataFrame, center=CITY_CENTER) -> folium.Map:
    """Builds a folium map with a HeatMap layer over every report's
    location.

    WHY folium over plotly.express.density_mapbox: folium (Leaflet.js)
    needs no Mapbox access token and renders straight to a standalone
    HTML file, which fits "print/save a sample output for verification"
    better than a chart that needs a token to tile properly.

    WHY weight by severity: a HeatMap that treats every point equally
    would show the same picture for a street with ten thefts as for one
    with ten homicides; weighting each point by a numeric severity score
    makes the visual density reflect impact, not just raw count.
    """
    severity_weight = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
    points = [
        [row.location_lat, row.location_lng, severity_weight.get(row.severity, 1)]
        for row in df.itertuples()
    ]

    fmap = folium.Map(location=list(center), zoom_start=12, tiles="OpenStreetMap")
    HeatMap(points, radius=12, blur=18, max_zoom=13).add_to(fmap)
    return fmap


def density_by_area(df: pd.DataFrame) -> pd.DataFrame:
    """Area-level summary a Streamlit dashboard can render as a ranked
    table or bar chart alongside the map itself."""
    summary = (
        df.groupby("area")
        .agg(report_count=("report_id", "count"),
             avg_lat=("location_lat", "mean"),
             avg_lng=("location_lng", "mean"))
        .sort_values("report_count", ascending=False)
        .reset_index()
    )
    return summary


def main():
    engine = get_engine()
    df = load_crime_locations(engine)

    fmap = build_heatmap(df)
    out_dir = ensure_output_dir()
    out_path = out_dir / "crime_heatmap.html"
    fmap.save(str(out_path))

    summary = density_by_area(df)

    print(f"Plotted {len(df)} geocoded crime reports.")
    print(f"Heatmap saved to: {out_path}")
    print("\nTop 5 areas by report count:")
    print(summary.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
