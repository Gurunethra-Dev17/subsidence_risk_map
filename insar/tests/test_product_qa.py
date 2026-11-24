from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from insar.product_qa import (
    ProductQAError,
    _coverage_percent,
    _geometry_pixel_intersection_areas,
    _ward_chart_rows,
    analyze_product,
)


def _synthetic_product(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    product = tmp_path / "S1_SYNTHETIC_INT80"
    product.mkdir()
    transform = from_origin(500_000, 3_100_000, 80, 80)
    profile = {
        "driver": "GTiff",
        "height": 20,
        "width": 20,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:32643",
        "transform": transform,
        "nodata": 0.0,
    }
    coherence = np.full((20, 20), 0.8, dtype=np.float32)
    coherence[:4, :] = 0.0
    phase = np.full((20, 20), 1.0, dtype=np.float32)
    phase[4, 0] = 20.0
    phase[:4, :] = 0.0
    components = np.ones((20, 20), dtype=np.float32)
    components[:4, :] = 0.0
    for suffix, array in (("corr", coherence), ("unw_phase", phase), ("conncomp", components)):
        with rasterio.open(product / f"S1_SYNTHETIC_{suffix}.tif", "w", **profile) as dataset:
            dataset.write(array, 1)
    (product / f"{product.name}.txt").write_text(
        "Reference Granule: S1_20261104T125446_VV_TEST\n"
        "Secondary Granule: S1_20261116T125445_VV_TEST\n"
        "Reference Pass Direction: ASCENDING\n"
        "Secondary Pass Direction: ASCENDING\n"
        "Reference Orbit Number: 5318\n"
        "Secondary Orbit Number: 5493\n"
        "Range looks: 20\nAzimuth looks: 4\nWater mask: no\n",
        encoding="utf-8",
    )
    (product / "S1_SYNTHETIC_README.md.txt").write_text(
        "ASF DAAC HyP3 2026\nplugin version 3.0.2\nISCE release 2.6.5\n"
        "Processing Date/Time: 2026-11-24T19:22:26+00:00\n",
        encoding="utf-8",
    )
    wards = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:32643"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"ward_id": "131", "ward_name": "BIJWASAN"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [500_000, 3_100_000],
                            [500_800, 3_100_000],
                            [500_800, 3_098_400],
                            [500_000, 3_098_400],
                            [500_000, 3_100_000],
                        ]
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"ward_id": "133", "ward_name": "MAHIPALPUR"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [500_800, 3_100_000],
                            [501_600, 3_100_000],
                            [501_600, 3_098_400],
                            [500_800, 3_098_400],
                            [500_800, 3_100_000],
                        ]
                    ],
                },
            },
        ],
    }
    wards_path = tmp_path / "wards.geojson"
    wards_path.write_text(json.dumps(wards), encoding="utf-8")
    c2_path = tmp_path / "ward_summary.json"
    c2_path.write_text(
        json.dumps(
            {
                "contract": "C2@1.0",
                "meta": {"data_vintage": "synthetic"},
                "wards": [
                    {"ward_id": "131", "ward_name": "BIJWASAN", "status": "ranked", "rank": 1},
                    {"ward_id": "133", "ward_name": "MAHIPALPUR", "status": "ranked", "rank": 2},
                ],
            }
        ),
        encoding="utf-8",
    )
    return product, wards_path, c2_path


def test_analyze_product_writes_masked_overlay_coverage_and_metadata(tmp_path, monkeypatch):
    monkeypatch.delenv("PROJ_LIB", raising=False)
    monkeypatch.delenv("PROJ_DATA", raising=False)
    product, wards, c2 = _synthetic_product(tmp_path)
    output = tmp_path / "qa"

    result = analyze_product(
        product_dir=product,
        wards_path=wards,
        c2_path=c2,
        output_dir=output,
        coherence_threshold=0.5,
    )

    assert result["product"]["crs"] == "EPSG:32643"
    assert result["product"]["raster"]["pixel_spacing_m"] == [80.0, 80.0]
    assert result["thresholds"]["exploratory_thresholds"]["0.50"]["usable_pixels"] == 320
    assert (
        result["geographic_coverage"]["targets"]["131"]["usable_pixels_by_coherence_threshold"][
            "0.50"
        ]
        == 160
    )
    assert result["api_fresh_data_status"] == "processed_not_validated"
    assert result["fresh_data_check"] == "not_run"
    assert (output / "qa_overview.png").is_file()
    assert (output / "ward_coverage.png").is_file()
    assert (output / "los_overlay.png").is_file()
    assert (output / "overlay_manifest.json").is_file()
    manifest = json.loads((output / "overlay_manifest.json").read_text(encoding="utf-8"))
    assert manifest["crs"] == "EPSG:4326"
    assert len(manifest["maplibre_corners_lon_lat"]) == 4
    assert manifest["valid_pixels"] > 0
    assert manifest["reference_acquisition_date"] == "2026-11-04"
    assert manifest["temporal_separation_days"] == 12
    assert manifest["units"].startswith("cm relative line-of-sight")
    assert manifest["sign_convention"] == "positive toward sensor; negative away from sensor"
    assert manifest["source_archive"] is None
    assert "BIJWASAN" in manifest["target_ward_coverage"]
    assert manifest["display_saturation"]["pixels_below_lower_limit"] > 0
    assert "saturate" in manifest["display_saturation"]["color_behavior"]
    assert "0 at the midpoint" in manifest["frontend_legend_recommendation"]
    assert manifest["measured_los_range_cm"][0] < manifest["color_scale_los_cm"][0]
    assert (
        manifest["sha256"] == hashlib.sha256((output / "los_overlay.png").read_bytes()).hexdigest()
    )
    from PIL import Image

    with Image.open(output / "los_overlay.png") as png:
        assert png.mode == "RGBA"
        assert png.size == (manifest["width"], manifest["height"])
        assert set(np.unique(np.asarray(png.getchannel("A")))) == {0, 210}
    import rasterio

    with rasterio.open(output / "los_relative_cm_masked.tif") as masked:
        masked_values = masked.read(1)
        assert masked.crs.to_epsg() == 32643
        with rasterio.open(product / "S1_SYNTHETIC_unw_phase.tif") as source:
            assert masked.transform == source.transform
        assert np.isclose(masked_values[4, 0], -20 * 2.8 / (2 * np.pi), rtol=1e-6)
        assert np.nanmin(masked_values) < manifest["color_scale_los_cm"][0]
    corners = manifest["maplibre_corners_lon_lat"]
    bounds = manifest["bbox_west_south_east_north"]
    assert corners == [
        [bounds[0], bounds[3]],
        [bounds[2], bounds[3]],
        [bounds[2], bounds[1]],
        [bounds[0], bounds[1]],
    ]
    assert (
        result["geographic_coverage"][
            "usable_pixel_intersection_area_pct_of_ward_union_by_coherence_threshold"
        ]["0.50"]
        <= 100
    )
    assert (output / "PERSON_C_HANDOFF.md").is_file()
    assert (output / "SHA256SUMS.txt").is_file()


def test_analyze_product_rejects_missing_product_without_emitting_success(tmp_path):
    output = tmp_path / "qa"
    with pytest.raises(ProductQAError, match="product directory does not exist"):
        analyze_product(
            product_dir=tmp_path / "missing",
            wards_path=tmp_path / "wards.geojson",
            c2_path=tmp_path / "ward_summary.json",
            output_dir=output,
        )
    assert not output.exists()


def test_pixel_intersection_area_accounts_for_small_ward_and_boundary_cells():
    from rasterio.transform import from_origin
    from shapely.geometry import box

    transform = from_origin(0, 80, 80, 80)
    rows, cols, areas = _geometry_pixel_intersection_areas(box(20, 20, 40, 40), (1, 2), transform)
    assert list(zip(rows, cols, strict=True)) == [(0, 0)]
    assert areas.tolist() == [400.0]
    assert _coverage_percent(float(areas.sum()), 400.0) == 100.0

    rows, cols, areas = _geometry_pixel_intersection_areas(box(70, 20, 90, 40), (1, 2), transform)
    assert list(zip(rows, cols, strict=True)) == [(0, 0), (0, 1)]
    assert areas.tolist() == [200.0, 200.0]
    assert _coverage_percent(float(areas.sum()), 400.0) == 100.0

    rows, cols, areas = _geometry_pixel_intersection_areas(box(300, 20, 320, 40), (1, 2), transform)
    assert rows.size == cols.size == areas.size == 0


def test_coverage_rejects_area_overrun_instead_of_clamping():
    assert _coverage_percent(100.0 + 1e-11, 100.0) == 100.0
    with pytest.raises(ProductQAError, match="exceeds its ward geometry"):
        _coverage_percent(100.01, 100.0)


def test_ward_chart_selects_top_fifteen_and_both_target_wards():
    wards = [
        {
            "ward_id": str(index),
            "usable_pixel_intersection_area_pct_of_full_ward": float(index),
        }
        for index in range(1, 21)
    ]
    wards.extend(
        [
            {"ward_id": "131", "usable_pixel_intersection_area_pct_of_full_ward": 0.1},
            {"ward_id": "133", "usable_pixel_intersection_area_pct_of_full_ward": 0.2},
        ]
    )
    selected = _ward_chart_rows(wards)
    assert len(selected) == 17
    assert {"131", "133"}.issubset({row["ward_id"] for row in selected})
    assert {str(index) for index in range(6, 21)}.issubset({row["ward_id"] for row in selected})
