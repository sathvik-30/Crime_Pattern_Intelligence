"""
Geographic page (Phase 5, page 2 of 5): the heatmap from
analytics/heatmap.py with the DBSCAN cluster overlay from
analytics/hotspot_clustering.py on one map, filterable by date range and
crime type (area is offered too, for consistency with the other pages).
"""

import sys
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

# Make dashboard/ importable regardless of how Streamlit executed this
# file -- see dashboard/app.py's identical bootstrap for why this can't
# just assume a fixed number of parent directories.
_here = Path(__file__).resolve()
for _candidate in [_here.parent, *_here.parents]:
    if (_candidate / "common.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from common import date_range_filter, get_areas, get_crime_types, get_engine

from analytics.heatmap import build_heatmap, density_by_area, load_crime_locations
from analytics.hotspot_clustering import find_hotspots, load_locations, summarize_clusters

st.set_page_config(page_title="Geographic | Crime Pattern Intelligence", layout="wide")

CLUSTER_PALETTE = [
    "red", "blue", "green", "purple", "orange", "darkred",
    "cadetblue", "darkgreen", "darkblue", "black",
]


@st.cache_data(ttl=300)
def load_filtered_locations(_engine, date_from, date_to, crime_types, areas):
    """Backs the heatmap layer -- same loader Phase 4's heatmap.py uses
    standalone, now with real filter values instead of None."""
    return load_crime_locations(
        _engine, date_from=date_from, date_to=date_to,
        crime_types=crime_types or None, areas=areas or None,
    )


@st.cache_data(ttl=300)
def load_filtered_clusters(_engine, date_from, date_to, crime_types, areas):
    """Backs the DBSCAN overlay -- re-clusters the filtered subset rather
    than filtering a fixed, whole-table clustering after the fact, so a
    narrowed date range or crime type actually changes what DBSCAN sees."""
    df = load_locations(
        _engine, date_from=date_from, date_to=date_to,
        crime_types=crime_types or None, areas=areas or None,
    )
    labeled = find_hotspots(df)
    summary = summarize_clusters(labeled)
    return labeled, summary


def add_cluster_overlay(fmap: folium.Map, labeled) -> folium.Map:
    """Adds DBSCAN cluster points as a toggleable layer on top of the
    heatmap already on fmap. Noise points (cluster == -1) are left off
    the overlay entirely -- they're explicitly "not part of a hotspot,"
    which is the whole point of using DBSCAN over k-means here (see
    hotspot_clustering.find_hotspots's docstring); drawing them would
    just add clutter with no hotspot signal.
    """
    cluster_layer = folium.FeatureGroup(name="DBSCAN hotspot clusters", show=True)
    clustered_only = labeled[labeled["cluster"] != -1]

    for row in clustered_only.itertuples():
        color = CLUSTER_PALETTE[row.cluster % len(CLUSTER_PALETTE)]
        folium.CircleMarker(
            location=[row.location_lat, row.location_lng],
            radius=4,
            color=color,
            fill=True,
            fill_opacity=0.8,
            popup=f"{row.area} / {row.crime_type} (cluster {row.cluster})",
        ).add_to(cluster_layer)

    cluster_layer.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap


def main():
    st.title("Geographic")
    st.caption("Crime density heatmap with DBSCAN hotspot clusters overlaid")

    engine = get_engine()
    crime_type_options = get_crime_types(engine)
    area_options = get_areas(engine)

    with st.expander("Filters", expanded=True):
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            date_from, date_to = date_range_filter(engine, key_prefix="geo")
        with col2:
            selected_crime_types = st.multiselect(
                "Crime type", options=crime_type_options, default=[], key="geo_crime_types"
            )
        with col3:
            selected_areas = st.multiselect(
                "Area", options=area_options, default=[], key="geo_areas"
            )

    heat_df = load_filtered_locations(engine, date_from, date_to, selected_crime_types, selected_areas)

    if heat_df.empty:
        st.info("No geocoded crime reports match the current filters.")
        return

    labeled, cluster_summary = load_filtered_clusters(
        engine, date_from, date_to, selected_crime_types, selected_areas
    )

    fmap = build_heatmap(heat_df)
    fmap = add_cluster_overlay(fmap, labeled)

    col_map, col_side = st.columns([3, 1])
    with col_map:
        st_folium(fmap, use_container_width=True, height=560, returned_objects=[])

    with col_side:
        st.metric("Reports plotted", f"{len(heat_df):,}")
        n_noise = int((labeled["cluster"] == -1).sum())
        n_clusters = cluster_summary.shape[0]
        st.metric("Hotspot clusters found", n_clusters)
        st.metric("Noise points (no hotspot)", f"{n_noise:,}")

        st.markdown("**Top areas by report count**")
        st.dataframe(density_by_area(heat_df).head(8), hide_index=True, width="stretch")

    if not cluster_summary.empty:
        st.subheader("Hotspot clusters, ranked by size")
        st.dataframe(cluster_summary, hide_index=True, width="stretch")


main()
