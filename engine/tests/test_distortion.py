"""Synthetic unit and integration checks for A3 building distortion."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from engine.distortion import (
    DistortionError,
    _classify,
    _pair_distortion,
    _ratio_string,
    compute_building_distortion,
)


def _geopandas_for_integration():
    try:
        import geopandas
    except ImportError as exc:
        if "Application Control policy has blocked this file" in str(exc):
            pytest.skip(f"local geospatial DLL blocked by environment policy: {exc}")
        raise
    return geopandas


def _inputs(point_offsets, rates, footprint_offsets, buffer_m=5.0):
    geopandas = _geopandas_for_integration()
    from shapely.geometry import Point, box

    base_x, base_y = 500_000.0, 3_100_000.0
    points = geopandas.GeoDataFrame(
        {"pt_id": [f"pt-{index}" for index in range(len(point_offsets))],
         "vlm_mm_yr": rates},
        geometry=[Point(base_x + offset, base_y) for offset in point_offsets],
        crs="EPSG:32643",
    )
    min_x, min_y, max_x, max_y = footprint_offsets
    buildings = geopandas.GeoDataFrame(
        {"bldg_id": ["bldg-a"]},
        geometry=[box(base_x + min_x, base_y + min_y, base_x + max_x, base_y + max_y)],
        crs="EPSG:32643",
    )
    cfg = SimpleNamespace(
        utm_epsg=32643,
        params={
            "pair_min_m": 10,
            "pair_max_m": 60,
            "footprint_buffer_m": buffer_m,
            "horizon_years": 10,
            "class_edges_ratio": [1000, 500],
        },
    )
    return buildings, points, cfg


def test_worked_pair_example_is_one_over_500_at_ten_years():
    beta_rate = _pair_distortion(-10.0, -6.0, 20.0)
    beta_horizon = beta_rate * 10

    assert beta_rate == pytest.approx(0.0002)
    assert beta_horizon == pytest.approx(0.002)
    assert _ratio_string(beta_horizon) == "1/500"
    assert _classify(beta_horizon, (1000, 500)) == "inspect"


def test_public_distortion_matches_c1_regression_snapshot_and_pair_membership():
    # The buffered footprint contains the first two points. Every pair except
    # the final pair touches that buffer; pairs with two inside points count once.
    buildings, points, cfg = _inputs(
        point_offsets=[0, 20, 40, 60],
        rates=[-10.0, -6.0, -2.0, 2.0],
        footprint_offsets=(-2, -2, 16, 2),
    )

    result = compute_building_distortion(buildings, points, cfg)

    assert result.columns.tolist() == [
        "bldg_id", "n_pairs", "beta_rate_per_yr", "beta_horizon",
        "beta_ratio_horizon", "beta_class",
    ]
    assert result["bldg_id"].tolist() == ["bldg-a"]
    assert result.loc[0, "n_pairs"] == 5
    assert result.loc[0, "beta_rate_per_yr"] == pytest.approx(0.0002)
    assert result.loc[0, "beta_horizon"] == pytest.approx(0.002)
    assert result.loc[0, "beta_ratio_horizon"] == "1/500"
    assert result.loc[0, "beta_class"] == "inspect"
    assert result.attrs["horizon_years"] == 10


def test_fewer_than_three_pairs_keep_pair_count_but_null_distortion_fields():
    buildings, points, cfg = _inputs(
        point_offsets=[0, 20, 40],
        rates=[-10.0, -6.0, -2.0],
        footprint_offsets=(-2, -2, 2, 2),
    )

    result = compute_building_distortion(buildings, points, cfg)

    assert result.loc[0, "n_pairs"] == 2
    assert pd.isna(result.loc[0, "beta_rate_per_yr"])
    assert pd.isna(result.loc[0, "beta_horizon"])
    assert result.loc[0, "beta_ratio_horizon"] is None
    assert result.loc[0, "beta_class"] is None


@pytest.mark.parametrize(
    ("beta_horizon", "expected_class"),
    [(0.002, "inspect"), (0.001, "watch"), (0.0005, "low"), (0.0, "low")],
)
def test_classification_edges_are_inclusive(beta_horizon, expected_class):
    assert _classify(beta_horizon, (1000, 500)) == expected_class


def test_zero_distortion_has_finite_ratio_representation():
    assert _ratio_string(0.0) == "1/inf"


def test_point_order_and_uniform_sign_flip_do_not_change_pair_distortion():
    buildings, points, cfg = _inputs(
        point_offsets=[0, 20, 40, 60],
        rates=[-10.0, -6.0, -2.0, 2.0],
        footprint_offsets=(-2, -2, 16, 2),
    )
    reference = compute_building_distortion(buildings, points, cfg)
    transformed_points = points.iloc[::-1].copy()
    transformed_points["vlm_mm_yr"] *= -1

    transformed = compute_building_distortion(buildings, transformed_points, cfg)

    assert transformed.loc[0, "n_pairs"] == reference.loc[0, "n_pairs"]
    assert transformed.loc[0, "beta_rate_per_yr"] == pytest.approx(reference.loc[0, "beta_rate_per_yr"])
    assert transformed.loc[0, "beta_horizon"] == pytest.approx(reference.loc[0, "beta_horizon"])
    assert transformed.loc[0, "beta_class"] == reference.loc[0, "beta_class"]


def test_zero_distance_pair_is_rejected_by_pair_formula():
    with pytest.raises(DistortionError, match="distance must be finite and positive"):
        _pair_distortion(-10.0, -6.0, 0.0)
