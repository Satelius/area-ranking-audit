"""Build auditable measurements for a set of planned candidate points."""

from __future__ import annotations

import math
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree


def _ids(frame, field, label):
    if field not in frame:
        raise ValueError(f"{label}: missing ID field {field!r}")
    if frame[field].isna().any() or frame[field].astype(str).str.strip().eq("").any():
        raise ValueError(f"{label}: blank ID")
    ids = frame[field].astype(str)
    if ids.duplicated().any():
        raise ValueError(f"{label}: duplicate IDs")
    return ids


def _geometry(frame, label, allowed):
    if not isinstance(frame, gpd.GeoDataFrame) or frame.crs is None:
        raise ValueError(f"{label}: a GeoDataFrame with a declared CRS is required")
    geometry = frame.geometry
    if geometry.isna().any() or geometry.is_empty.any() or (~geometry.is_valid).any():
        raise ValueError(f"{label}: missing, empty or invalid geometry")
    if not geometry.geom_type.isin(allowed).all():
        raise ValueError(f"{label}: expected geometries {sorted(allowed)}")


def _metric_crs(frame):
    crs = frame.crs
    if not crs.is_projected or len(crs.axis_info) < 2:
        raise ValueError("candidates: projected CRS in metres required")
    if any(not math.isclose(axis.unit_conversion_factor or 0, 1) for axis in crs.axis_info[:2]):
        raise ValueError("candidates: CRS units must be metres")


def _region_assignments(points, regions, region_field):
    regions = regions.to_crs(points.crs).copy()
    regions[region_field] = _ids(regions, region_field, "regions")
    tree = STRtree(regions.geometry.to_numpy())
    pairs = tree.query(points.geometry.to_numpy(), predicate="intersects")
    counts = np.bincount(pairs[0], minlength=len(points))
    if (counts != 1).any():
        raise ValueError(f"candidate-to-region assignment must be unique: {(counts == 0).sum()} outside and {(counts > 1).sum()} ambiguous; resolve boundary overlaps explicitly")
    assigned = np.empty(len(points), dtype=object)
    assigned[pairs[0]] = regions[region_field].to_numpy()[pairs[1]]
    return assigned


def _facilities(spec, crs):
    facilities = spec.get("data")
    _geometry(facilities, spec["name"], {"Point", "MultiPoint", "Polygon", "MultiPolygon"})
    facilities = facilities.to_crs(crs).copy()
    dedup_field = spec.get("deduplicate_by")
    if dedup_field:
        if dedup_field not in facilities or facilities[dedup_field].isna().any():
            raise ValueError(f"{spec['name']}: deduplication ID missing or null")
        for _, group in facilities.groupby(dedup_field, sort=False):
            if len(group) > 1 and not shapely.equals(group.geometry.to_numpy(), group.geometry.iloc[0]).all():
                raise ValueError(f"{spec['name']}: duplicate IDs have different geometries")
        facilities = facilities.drop_duplicates(dedup_field)
    return facilities


def _spatial_values(points, spec):
    method = spec["method"]
    if spec.get("coverage_known") is not True:
        return np.full(len(points), np.nan), np.full(len(points), "coverage_unknown", dtype=object)
    facilities = _facilities(spec, points.crs)
    if method == "count_within":
        radius = spec.get("radius_m")
        if not isinstance(radius, (int, float)) or not math.isfinite(radius) or radius < 0:
            raise ValueError(f"{spec['name']}: radius_m must be finite and nonnegative")
        if not facilities.geom_type.isin(["Point", "MultiPoint"]).all():
            raise ValueError(f"{spec['name']}: counts require point facilities")
        if facilities.empty:
            return np.zeros(len(points)), np.full(len(points), "ok", dtype=object)
        pairs = STRtree(facilities.geometry.to_numpy()).query(points.geometry.to_numpy(), predicate="dwithin", distance=radius)
        return np.bincount(pairs[0], minlength=len(points)).astype(float), np.full(len(points), "ok", dtype=object)
    if facilities.empty:
        return np.full(len(points), np.nan), np.full(len(points), "no_facilities", dtype=object)
    tree = STRtree(facilities.geometry.to_numpy())
    pairs, distances = tree.query_nearest(points.geometry.to_numpy(), return_distance=True, all_matches=False)
    result = np.full(len(points), np.nan)
    result[pairs[0]] = distances
    return result, np.full(len(points), "ok", dtype=object)


def _table_values(points, id_field, spec):
    table = spec.get("data")
    if not isinstance(table, pd.DataFrame):
        raise ValueError(f"{spec['name']}: data must be a pandas table")
    table_id = spec.get("id_field", id_field)
    value_field = spec.get("value_field")
    ids = _ids(table, table_id, spec["name"])
    if value_field not in table:
        raise ValueError(f"{spec['name']}: missing value field")
    original = table[value_field]
    numbers = pd.to_numeric(original, errors="coerce")
    if (original.notna() & numbers.isna()).any():
        raise ValueError(f"{spec['name']}: non-numeric value")
    lookup = pd.Series(numbers.to_numpy(), index=ids)
    result = lookup.reindex(points[id_field]).to_numpy(dtype=float, na_value=np.nan)
    if np.isinf(result).any():
        raise ValueError(f"{spec['name']}: infinite value")
    status = np.where(pd.isna(result), "missing_measurement", "ok")
    return result, status


def build_indicators(candidates, regions, specs, id_field="candidate_id", region_field="region_id"):
    """Return every candidate with raw indicator values and per-indicator status.

    Metric geometry calculations use the candidate CRS. The specs are dictionaries:
    {'name', 'method': 'count_within'|'nearest'|'table', 'data', ...}.
    Spatial specs require coverage_known=True to assert dataset coverage, and may
    specify deduplicate_by. Count specs additionally specify radius_m. Table specs
    specify value_field and optionally id_field. The caller records source and unit.
    """
    _geometry(candidates, "candidates", {"Point"})
    _geometry(regions, "regions", {"Polygon", "MultiPolygon"})
    _metric_crs(candidates)
    result = candidates.copy().reset_index(drop=True)
    result[id_field] = _ids(result, id_field, "candidates")
    if region_field in result:
        raise ValueError(f"candidates already contain {region_field!r}; avoid overwriting it")
    result[region_field] = _region_assignments(result, regions, region_field)
    for spec in specs:
        name = spec.get("name", "")
        method = spec.get("method")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or name in result or name + "__status" in result:
            raise ValueError(f"invalid or duplicated indicator name {name!r}")
        if method not in {"count_within", "nearest", "table"}:
            raise ValueError(f"{name}: unsupported method {method!r}")
        if method == "table":
            values, status = _table_values(result, id_field, spec)
        else:
            values, status = _spatial_values(result, spec)
        result[name] = values
        result[name + "__status"] = status
    return result
