"""Unit and integration coverage for A2 point-to-building assignment."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from engine.assign import _assign_projected, _weighted_quantile, assign_points_to_buildings


def _geopandas_for_integration():
    try:
        import geopandas
    except ImportError as exc:
        if "Application Control policy has blocked this file" in str(exc):
            pytest.skip(f"local geospatial DLL blocked by environment policy: {exc}")
        raise
    return geopandas


def test_weighted_quantile_uses_inverse_distance_weights():
    # The closest observation has enough weight to move the weighted median
    # below the ordinary median (-5).
    median = _weighted_quantile(
        values=np.array([-5.0, -20.0, 10.0]),
        weights=np.array([1.0, 0.5, 0.1]),
        quantile=0.5,
    )

    assert median == pytest.approx(-9.0)


def test_projected_assignment_counts_neighbors_estimates_and_sparse_rows():
    point_xy = np.array([[0.0, 0.0], [0.0, 0.0], [4.0, 0.0]])
    rates = np.array([-9.0, -5.0, -100.0])
    building_xy = np.array([[0.0, 0.0], [10.0, 0.0], [np.nan, np.nan]])

    counts, estimates, iqrs = _assign_projected(
        building_xy, point_xy, rates, radius_m=5, min_points=2, chunk_size=1,
    )

    np.testing.assert_array_equal(counts, [3, 0, 0])
    assert estimates[0] == pytest.approx(-7.0)
    assert iqrs[0] == pytest.approx(4.0)
    assert np.isnan(estimates[1:]).all()
    assert np.isnan(iqrs[1:]).all()


def test_projected_assignment_empty_points_marks_all_buildings_sparse():
    counts, estimates, iqrs = _assign_projected(
        np.array([[0.0, 0.0], [1.0, 1.0]]),
        np.empty((0, 2)),
        np.empty(0),
        radius_m=10,
        min_points=1,
        chunk_size=100,
    )

    np.testing.assert_array_equal(counts, [0, 0])
    assert np.isnan(estimates).all()
    assert np.isnan(iqrs).all()


def test_public_assignment_returns_contract_columns_in_building_order():
    geopandas = _geopandas_for_integration()
    from shapely.geometry import Point, box

    buildings = geopandas.GeoDataFrame(
        {"bldg_id": ["bldg-a", "bldg-b"]},
        geometry=[box(499999, 3099999, 500001, 3100001),
                  box(500009, 3099999, 500011, 3100001)],
        crs="EPSG:32643",
    )
    points = geopandas.GeoDataFrame(
        {"vlm_mm_yr": [-9.0, -5.0, -100.0]},
        geometry=[Point(500000, 3100000), Point(500000, 3100000), Point(500004, 3100000)],
        crs="EPSG:32643",
    )
    cfg = SimpleNamespace(utm_epsg=32643, params={"radius_m": 5, "min_points": 2})

    assigned = assign_points_to_buildings(buildings, points, cfg, chunk_size=1)

    assert assigned.columns.tolist() == [
        "bldg_id", "n_points", "vlm_mm_yr", "vlm_iqr_mm_yr", "sparse",
    ]
    assert assigned["bldg_id"].tolist() == ["bldg-a", "bldg-b"]
    assert assigned["n_points"].tolist() == [3, 0]
    assert assigned.loc[0, "vlm_mm_yr"] == pytest.approx(-7.0)
    assert assigned.loc[0, "vlm_iqr_mm_yr"] == pytest.approx(4.0)
    assert assigned["sparse"].tolist() == [False, True]
