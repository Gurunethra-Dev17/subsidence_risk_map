"""Unit and integration coverage for A1 configuration and point loading."""
from __future__ import annotations

import csv

import numpy as np
import pytest

from engine.io import InputError, _bbox_mask, _normalize_vlm_values, load_config, load_vlm_points


def _geopandas_for_integration():
    try:
        import geopandas
    except ImportError as exc:
        if "Application Control policy has blocked this file" in str(exc):
            pytest.skip(f"local geospatial DLL blocked by environment policy: {exc}")
        raise
    return geopandas


def test_delhi_c6_config_loads_expected_projection_and_bounds():
    from pathlib import Path

    cfg = load_config(str(Path(__file__).resolve().parents[2] / "configs" / "delhi.yaml"))

    assert cfg.contract == "C6@1.0"
    assert cfg.city == "delhi"
    assert cfg.utm_epsg == 32643
    assert cfg.bbox == (76.84, 28.4, 77.35, 28.89)
    assert cfg.params["radius_m"] == 100
    assert cfg.pack_dir.name == "delhi-pack-1.0.0"


@pytest.mark.parametrize(
    ("column", "input_values", "expected", "unit"),
    [
        ("vlm_mm_yr", [-10, 2.5], [-10, 2.5], "mm/yr"),
        ("vlm_cm_yr", [-1, 0.25], [-10, 2.5], "cm/yr"),
        ("vlm", [-1, 0.25], [-10, 2.5], "cm/yr"),
    ],
)
def test_vlm_source_units_normalize_to_mm_per_year(column, input_values, expected, unit):
    values, source_unit = _normalize_vlm_values(input_values, column)

    np.testing.assert_allclose(values, expected)
    assert source_unit == unit


def test_vlm_normalization_rejects_nonfinite_rate():
    with pytest.raises(InputError, match="finite"):
        _normalize_vlm_values([-1, float("nan")], "vlm_cm_yr")


def test_bbox_mask_includes_edges_and_excludes_outside_points():
    mask = _bbox_mask(
        np.array([76.84, 77.35, 77.36, 77.0]),
        np.array([28.4, 28.89, 28.6, 28.9]),
        (76.84, 28.4, 77.35, 28.89),
    )

    np.testing.assert_array_equal(mask, [True, True, False, False])


def test_load_vlm_points_converts_and_clips_csv_fixture(tmp_path):
    geopandas = _geopandas_for_integration()
    from types import SimpleNamespace

    path = tmp_path / "points.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["pt_id", "lon", "lat", "vlm", "source"])
        writer.writeheader()
        writer.writerows([
            {"pt_id": "inside-1", "lon": 77.0, "lat": 28.6, "vlm": -1.0, "source": "vt-in-v2"},
            {"pt_id": "edge-1", "lon": 77.1, "lat": 28.7, "vlm": 0.2, "source": "vt-in-v2"},
            {"pt_id": "outside-1", "lon": 78.0, "lat": 28.6, "vlm": -2.0, "source": "vt-in-v2"},
        ])
    cfg = SimpleNamespace(bbox=(76.84, 28.4, 77.35, 28.89), utm_epsg=32643)

    points = load_vlm_points(cfg, str(path))

    assert isinstance(points, geopandas.GeoDataFrame)
    assert points.crs.to_epsg() == 4326
    assert points["pt_id"].tolist() == ["inside-1", "edge-1"]
    assert points["vlm_mm_yr"].tolist() == [-10.0, 2.0]
    stats = points.attrs["load_stats"]
    assert stats.rows_read == 3
    assert stats.rows_in_bbox == 2
    assert stats.rows_clipped == 1
    assert stats.n_sinking == 1
    assert stats.n_rising == 1
    assert stats.utm_epsg == 32643
