import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box
from indicators import build_indicators


def layer(geometry, **columns):
    return gpd.GeoDataFrame(columns, geometry=geometry, crs="EPSG:3414")


def data():
    points = layer([Point(0, 0), Point(5, 0)], candidate_id=["a", "b"])
    regions = layer([box(-10, -10, 10, 10)], region_id=["R"])
    return points, regions


def test_counts_nearest_and_missing():
    points, regions = data()
    sites = layer([Point(0, 0), Point(0, 0), Point(3, 0)], site_id=["1", "1", "2"])
    park = layer([box(-1, -1, 1, 1)])
    table = pd.DataFrame({"candidate_id": ["a"], "distance": [42]})
    specs = [
        {"name": "shops", "method": "count_within", "data": sites, "radius_m": 3, "coverage_known": True, "deduplicate_by": "site_id"},
        {"name": "park", "method": "nearest", "data": park, "coverage_known": True},
        {"name": "road", "method": "table", "data": table, "value_field": "distance"},
        {"name": "unknown", "method": "nearest", "coverage_known": False},
    ]
    result = build_indicators(points, regions, specs)
    assert result.shops.tolist() == [2, 1]
    assert result.park.tolist() == [0, 4]
    assert result.road.iloc[0] == 42 and np.isnan(result.road.iloc[1])
    assert result.road__status.tolist() == ["ok", "missing_measurement"]
    assert result.unknown__status.tolist() == ["coverage_unknown", "coverage_unknown"]


def test_empty_layer_known_and_unknown():
    points, regions = data()
    empty = layer([], site_id=[])
    result = build_indicators(points, regions, [
        {"name": "count", "method": "count_within", "data": empty, "radius_m": 3, "coverage_known": True},
        {"name": "near", "method": "nearest", "data": empty, "coverage_known": True},
    ])
    assert result["count"].tolist() == [0, 0]
    assert result.near.isna().all() and (result.near__status == "no_facilities").all()


def test_boundary_or_duplicate_or_geographic_crs_rejected():
    points, regions = data()
    overlap = layer([box(-10, -10, 0, 10), box(0, -10, 10, 10)], region_id=["R", "S"])
    with pytest.raises(ValueError, match="ambiguous"):
        build_indicators(points, overlap, [])
    duplicate = pd.DataFrame({"candidate_id": ["a", "a"], "distance": [1, 2]})
    with pytest.raises(ValueError, match="duplicate"):
        build_indicators(points, regions, [{"name": "d", "method": "table", "data": duplicate, "value_field": "distance"}])
    with pytest.raises(ValueError, match="projected CRS"):
        build_indicators(points.to_crs(4326), regions, [])
