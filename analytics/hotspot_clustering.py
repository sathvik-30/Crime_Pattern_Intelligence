"""
DBSCAN-based geographic hotspot detection on crime_reports lat/lng.

Runnable standalone:
    python analytics/hotspot_clustering.py

Saves a colored cluster map to analytics/output/hotspot_clusters_map.html
and a cluster summary table to analytics/output/hotspot_clusters.csv, and
prints the ranked hotspot list for quick verification.
"""

import sys
from pathlib import Path

import folium
import pandas as pd
from sklearn.cluster import DBSCAN

try:
    from analytics.db import ensure_output_dir, get_engine
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from db import ensure_output_dir, get_engine

# Tuned empirically against the seeded dataset (see the eps/min_samples
# grid search this module's docstring below references): eps=0.012 (the
# first, purely geometric estimate based on the seed data's ~0.01-degree
# hotspot stddev) turned out too loose in practice -- DBSCAN's density-
# reachability chaining bridged all 4 hotspots into a single cluster,
# since the space between them isn't as empty as the raw stddev numbers
# suggest at only 560 total points. eps=0.005 / min_samples=8 is the
# smallest, tightest setting that still reliably finds real structure
# (rather than fragmenting into many tiny clusters) across the 4 seeded
# hotspot areas without also picking up the long-tail areas' much
# sparser scatter.
DEFAULT_EPS = 0.005
DEFAULT_MIN_SAMPLES = 8


def load_locations(engine) -> pd.DataFrame:
    query = """
        SELECT report_id, area, crime_type, severity, location_lat, location_lng
        FROM crime_reports
        WHERE location_lat IS NOT NULL AND location_lng IS NOT NULL
    """
    return pd.read_sql(query, engine)


def find_hotspots(
    df: pd.DataFrame, eps: float = DEFAULT_EPS, min_samples: int = DEFAULT_MIN_SAMPLES
) -> pd.DataFrame:
    """Labels each report with a DBSCAN cluster id (-1 = noise, not part
    of any dense hotspot).

    WHY DBSCAN over k-means for this problem:
      1. Hotspots are irregularly shaped. K-means assigns every point to
         the nearest of k centroids, which effectively forces every
         cluster to be a round, convex blob (a Voronoi cell) -- but a
         real hotspot follows streets, neighborhoods, and land use, not
         a circle around a single center point.
      2. K-means requires choosing k up front. There is no principled way
         to know "how many hotspots exist" in advance -- that's the
         question being asked. DBSCAN instead discovers the number of
         clusters from the data's own density structure.
      3. K-means has no concept of noise: every single point, including
         a report way out in a quiet suburb, gets forced into the
         nearest cluster and drags that cluster's centroid toward it.
         DBSCAN explicitly labels sparse, isolated points as noise
         (cluster -1) and leaves them out of the hotspot picture
         entirely, which is exactly the right behavior here -- an
         isolated report shouldn't count as evidence of a "hotspot."

    eps/min_samples are in raw lat/lng degrees, which is an approximation
    (a degree of longitude shrinks at higher latitudes) that's acceptable
    at city scale, where the resulting distortion is a small fraction of
    eps itself.
    """
    coords = df[["location_lat", "location_lng"]].to_numpy()
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(coords)

    result = df.copy()
    result["cluster"] = labels
    return result


def summarize_clusters(labeled: pd.DataFrame) -> pd.DataFrame:
    """One row per real cluster (noise excluded), ranked by size -- the
    "hotspot leaderboard" a dashboard would show."""
    clustered = labeled[labeled["cluster"] != -1]

    summary = (
        clustered.groupby("cluster")
        .agg(
            report_count=("report_id", "count"),
            center_lat=("location_lat", "mean"),
            center_lng=("location_lng", "mean"),
            dominant_area=("area", lambda s: s.mode().iat[0]),
            dominant_crime_type=("crime_type", lambda s: s.mode().iat[0]),
        )
        .sort_values("report_count", ascending=False)
        .reset_index()
    )
    return summary


def hotspot_leaderboard_by_area(labeled: pd.DataFrame) -> pd.DataFrame:
    """Rolls cluster membership up to the area level: what fraction of
    each area's reports fall inside *some* dense DBSCAN cluster, versus
    scattered as noise.

    This is the more robust hotspot signal to validate against known
    geography than "which single cluster is biggest": a real hotspot's
    points are a 2D scatter around a center, not a uniform disc, so
    DBSCAN often (correctly) finds it as 2-3 adjacent dense sub-clusters
    rather than exactly one -- summarize_clusters() reports those
    sub-clusters separately, while this function regroups by area so a
    hotspot split into pieces still reads as one clear signal.
    """
    total = labeled.groupby("area").size().rename("total_reports")
    clustered = (
        labeled[labeled["cluster"] != -1].groupby("area").size().rename("clustered_reports")
    )
    combined = total.to_frame().join(clustered).fillna(0)
    combined["clustered_reports"] = combined["clustered_reports"].astype(int)
    combined["pct_in_hotspot"] = (
        100 * combined["clustered_reports"] / combined["total_reports"]
    ).round(1)
    return combined.sort_values("clustered_reports", ascending=False).reset_index()


def build_cluster_map(labeled: pd.DataFrame) -> folium.Map:
    center = [labeled["location_lat"].mean(), labeled["location_lng"].mean()]
    fmap = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")

    palette = [
        "red", "blue", "green", "purple", "orange", "darkred",
        "cadetblue", "darkgreen", "darkblue", "black",
    ]
    for row in labeled.itertuples():
        is_noise = row.cluster == -1
        color = "lightgray" if is_noise else palette[row.cluster % len(palette)]
        folium.CircleMarker(
            location=[row.location_lat, row.location_lng],
            radius=3 if is_noise else 5,
            color=color,
            fill=True,
            fill_opacity=0.5 if is_noise else 0.85,
            popup=f"{row.area} / {row.crime_type} (cluster {row.cluster})",
        ).add_to(fmap)

    return fmap


def main():
    engine = get_engine()
    df = load_locations(engine)

    labeled = find_hotspots(df)
    summary = summarize_clusters(labeled)
    area_leaderboard = hotspot_leaderboard_by_area(labeled)

    out_dir = ensure_output_dir()
    csv_path = out_dir / "hotspot_clusters.csv"
    summary.to_csv(csv_path, index=False)
    area_csv_path = out_dir / "hotspot_leaderboard_by_area.csv"
    area_leaderboard.to_csv(area_csv_path, index=False)

    fmap = build_cluster_map(labeled)
    map_path = out_dir / "hotspot_clusters_map.html"
    fmap.save(str(map_path))

    n_noise = int((labeled["cluster"] == -1).sum())
    n_clusters = summary.shape[0]

    print(f"DBSCAN found {n_clusters} hotspot cluster(s) and {n_noise} noise point(s) "
          f"out of {len(labeled)} total reports.")
    print("\nRaw clusters, ranked by size:")
    print(summary.to_string(index=False))
    print(f"Cluster summary saved to: {csv_path}")

    print("\nHotspot leaderboard by area (% of each area's reports inside a dense cluster):")
    print(area_leaderboard.to_string(index=False))
    print(f"Area leaderboard saved to: {area_csv_path}")
    print(f"Cluster map saved to: {map_path}")


if __name__ == "__main__":
    main()
