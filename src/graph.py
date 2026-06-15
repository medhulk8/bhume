"""Adjacency graph over village plots.

Primary edges: shared boundary vertices (snap tolerance).
Secondary: Delaunay centroid triangulation with distance cap (backstop for isolated plots).

Used by:
  - Phase 3 block-grow (BFS over neighbours)
  - Phase 4 seam detection (anchor-shift discordance on edges)
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
from scipy.spatial import Delaunay

SNAP_TOL = 1e-7        # degrees — coordinate rounding for shared-vertex detection (~1cm)
DELAUNAY_CAP_M = 500.0  # max centroid-to-centroid distance for Delaunay backstop edge


def build_adjacency(plots: gpd.GeoDataFrame, utm_crs: str) -> dict[str, set[str]]:
    """Build adjacency dict: plot_number → set of neighbouring plot_numbers.

    Two passes:
    1. Shared vertices: plots that share an exact (rounded) coordinate are adjacent.
    2. Delaunay backstop: add Delaunay edges within DELAUNAY_CAP_M for isolated plots
       (those with < 2 shared-vertex neighbours).

    Returns: adj[pn] = {pn1, pn2, ...}
    """
    adj: dict[str, set[str]] = defaultdict(set)

    # --- Pass 1: shared vertices ---
    coord_to_plots: dict[tuple, list[str]] = defaultdict(list)
    for pn, row in plots.iterrows():
        geom = row["geometry"]
        if geom is None or geom.is_empty:
            continue
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polys:
            rings = [poly.exterior] + list(poly.interiors)
            for ring in rings:
                for coord in ring.coords:
                    key = (round(coord[0], 7), round(coord[1], 7))
                    coord_to_plots[key].append(pn)

    for plots_sharing in coord_to_plots.values():
        if len(plots_sharing) < 2:
            continue
        unique = list(set(plots_sharing))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                adj[unique[i]].add(unique[j])
                adj[unique[j]].add(unique[i])

    # --- Pass 2: Delaunay backstop ---
    plots_u = plots.to_crs(utm_crs)
    centroids = {pn: (row["geometry"].centroid.x, row["geometry"].centroid.y)
                 for pn, row in plots_u.iterrows()
                 if row["geometry"] is not None and not row["geometry"].is_empty}
    pns = list(centroids.keys())
    coords = np.array([centroids[pn] for pn in pns])

    if len(coords) >= 4:
        tri = Delaunay(coords)
        for simplex in tri.simplices:
            for i in range(3):
                for j in range(i + 1, 3):
                    a, b = pns[simplex[i]], pns[simplex[j]]
                    ca, cb = np.array(centroids[a]), np.array(centroids[b])
                    dist = float(np.linalg.norm(ca - cb))
                    if dist <= DELAUNAY_CAP_M:
                        adj[a].add(b)
                        adj[b].add(a)

    # Ensure every plot has an entry (even if isolated)
    for pn in plots.index:
        if pn not in adj:
            adj[pn] = set()

    return dict(adj)


def plot_areas_utm(plots: gpd.GeoDataFrame, utm_crs: str) -> dict[str, float]:
    """Return {plot_number: area_m2} in UTM."""
    plots_u = plots.to_crs(utm_crs)
    return {pn: row["geometry"].area
            for pn, row in plots_u.iterrows()
            if row["geometry"] is not None and not row["geometry"].is_empty}


def plot_perimeters_utm(plots: gpd.GeoDataFrame, utm_crs: str) -> dict[str, float]:
    """Return {plot_number: perimeter_m} in UTM."""
    plots_u = plots.to_crs(utm_crs)
    return {pn: row["geometry"].length
            for pn, row in plots_u.iterrows()
            if row["geometry"] is not None and not row["geometry"].is_empty}


def outer_perimeter(block_pns: list[str], plots_u: gpd.GeoDataFrame) -> float:
    """Outer perimeter of a block (in UTM metres) — interior shared edges excluded.

    Uses unary_union of plot geometries; perimeter of the merged shape is the outer boundary.
    """
    from shapely.ops import unary_union
    geoms = [plots_u.loc[pn, "geometry"]
             for pn in block_pns
             if pn in plots_u.index and plots_u.loc[pn, "geometry"] is not None]
    if not geoms:
        return 0.0
    merged = unary_union(geoms)
    return float(merged.length)
