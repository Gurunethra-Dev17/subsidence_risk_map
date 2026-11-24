"""Bounded HTTP and privacy tests for the public ward PDF brief."""

from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4

import api.main as api_main
from api.data import APIData, DataPaths


def _ward(**changes):
    ward = {
        "ward_id": "ward-test-01",
        "ward_name": "North Demonstration Ward",
        "status": "ranked",
        "n_buildings": 20,
        "n_buildings_with_data": 18,
        "coverage_pct": 90,
        "share_sinking_gt4": 0.25,
        "vlm_median_mm_yr": -2.5,
        "beta_p90_horizon": 0.002,
        "beta_p90_ratio_horizon": "1/500",
        "gw_stage_pct": None,
        "gw_category": None,
        "score": 72.5,
        "rank": 2,
        "rank_p05": 1,
        "rank_p95": 4,
        "flags": ["groundwater_missing", "sparse_points"],
    }
    ward.update(changes)
    return ward


def _cell(cell_id: str, rank: int | None, **properties):
    cell_properties = {
        "cell_id": cell_id,
        "ward_id": "ward-test-01",
        "n_buildings": 8,
        "suppressed": False,
        "vlm_median_mm_yr": -2.1,
        "beta_p90_horizon": 0.0015,
        "share_sinking_gt4": 0.25,
        "cell_score": 64.0,
        "cell_rank_in_ward": rank,
    }
    cell_properties.update(properties)
    return {"type": "Feature", "geometry": None, "properties": cell_properties}


def _polygon(x: float, y: float, size: float = 0.001):
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [x, y],
                [x + size, y],
                [x + size, y + size],
                [x, y + size],
                [x, y],
            ]
        ],
    }


def _geo_cell(cell_id: str, geometry, **properties):
    feature = _cell(cell_id, 1)
    feature["geometry"] = geometry
    feature["properties"].update(properties)
    return feature


@pytest.fixture
def brief_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    summary_path = tmp_path / "ward_summary.json"
    cells_path = tmp_path / "cells.geojson"
    summary_path.write_text(
        json.dumps({
            "contract": "C2@1.0",
            "meta": {
                "city": "delhi",
                "data_vintage": "2015-2023",
                "generated_utc": "2026-11-11T09:00:00Z",
                "engine_version": "engine-test-1",
                "params": {},
                "weights": {"i1": 0.3, "i2": 0.35, "i3": 0.2, "i4": 0.15},
                "n_wards": 1,
                "n_ranked": 1,
            },
            "wards": [_ward()],
        }),
        encoding="utf-8",
    )
    cells_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": [_cell("cell-A", 1)]}),
        encoding="utf-8",
    )
    store = APIData(
        DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )
    )
    monkeypatch.setattr(api_main, "data_store", store)
    return TestClient(api_main.app)


def _pdf_text(response) -> str:
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) == 1
    assert float(reader.pages[0].mediabox.width) == pytest.approx(A4[0])
    assert float(reader.pages[0].mediabox.height) == pytest.approx(A4[1])
    return re.sub(r"\s+", " ", reader.pages[0].extract_text() or "")


def test_known_ward_returns_single_page_pdf_with_required_content_and_headers(
    brief_client: TestClient, tmp_path: Path
) -> None:
    before = set(tmp_path.iterdir())
    response = brief_client.get("/api/v1/wards/ward-test-01/brief.pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["Cache-Control"] == "no-store"
    text = _pdf_text(response)
    assert "North Demonstration Ward" in text
    assert "ward-test-01" in text
    assert "2015-2023" in text
    assert "engine-test-1" in text
    assert (
        "ranks areas for inspection; does not certify any building; "
        "projections are scenarios under constant rates"
    ) in text
    assert set(tmp_path.iterdir()) == before


def test_vector_map_renders_polygon_and_multipolygon_with_score_and_suppression_legend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    cells_path = tmp_path / "cells.geojson"
    multipolygon = {
        "type": "MultiPolygon",
        "coordinates": [
            _polygon(77.10, 28.55)["coordinates"],
            _polygon(77.103, 28.55)["coordinates"],
        ],
    }
    cells = [
        _geo_cell("scored-polygon", _polygon(77.10, 28.55), cell_score=75),
        _geo_cell("scored-multipolygon", multipolygon, cell_score=40),
        _geo_cell(
            "suppressed-cell",
            _polygon(77.106, 28.55),
            suppressed=True,
            cell_score=987654,
            beta_p90_horizon=876543,
        ),
    ]
    summary_path.write_text(
        json.dumps({"contract": "C2@1.0", "meta": {}, "wards": [_ward()]}),
        encoding="utf-8",
    )
    cells_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": cells}), encoding="utf-8"
    )
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )),
    )

    response = TestClient(api_main.app).get("/api/v1/wards/ward-test-01/brief.pdf")
    reader = PdfReader(BytesIO(response.content))
    text = re.sub(r"\s+", " ", reader.pages[0].extract_text() or "")
    vector_content = reader.pages[0].get_contents().get_data()

    assert response.status_code == 200
    assert len(reader.pages) == 1
    assert "Ward-assigned grid-cell overview" in text
    assert "not an administrative boundary" in text
    assert "Lower to higher relative inspection priority" in text
    assert "Suppressed: no score displayed" in text
    assert "not collapse probability" in text
    assert b" m" in vector_content and b" l" in vector_content and b"h" in vector_content
    assert b"987654" not in vector_content and b"876543" not in vector_content
    assert "987654" not in text and "876543" not in text


def test_suppressed_score_is_never_read_for_map_rendering() -> None:
    from api.brief import _CellMap

    class SuppressedProperties(dict):
        def get(self, key, default=None):
            if key == "cell_score":
                raise AssertionError("suppressed score must not be read")
            return super().get(key, default)

    cells = {
        "features": [
            {
                "type": "Feature",
                "geometry": _polygon(77.1, 28.5),
                "properties": SuppressedProperties({"suppressed": True}),
            }
        ]
    }
    assert _CellMap(cells)._cells[0][1:] == (True, None)


def test_invalid_or_missing_cell_geometry_displays_map_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    cells_path = tmp_path / "cells.geojson"
    invalid = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]],
    }
    cells_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _geo_cell("empty", {"type": "Polygon", "coordinates": []}),
                    _geo_cell("self-crossing", invalid),
                    _cell("missing", 1),
                ],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"contract": "C2@1.0", "meta": {}, "wards": [_ward()]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )),
    )

    response = TestClient(api_main.app).get("/api/v1/wards/ward-test-01/brief.pdf")
    reader = PdfReader(BytesIO(response.content))
    text = re.sub(r"\s+", " ", reader.pages[0].extract_text() or "")
    assert response.status_code == 200
    assert "Map unavailable: no usable cell geometry" in text


def test_insufficient_coverage_keeps_map_and_score_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    cells_path = tmp_path / "cells.geojson"
    ward = _ward(
        status="insufficient_data",
        rank=None,
        score=None,
        rank_p05=None,
        rank_p95=None,
        n_buildings_with_data=0,
        coverage_pct=0,
    )
    cells_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [_geo_cell("unscored-cell", _polygon(77.1, 28.5), cell_score=None)],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"contract": "C2@1.0", "meta": {}, "wards": [ward]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )),
    )

    response = TestClient(api_main.app).get("/api/v1/wards/ward-test-01/brief.pdf")
    reader = PdfReader(BytesIO(response.content))
    text = re.sub(r"\s+", " ", reader.pages[0].extract_text() or "")
    assert response.status_code == 200
    assert "Inspection Index Unavailable" in text
    assert "This ward is marked insufficient_data and is not ranked" in text
    assert "Insufficient evidence is not evidence of low risk" in text
    assert "Map unavailable" not in text


def test_unknown_ward_uses_c4_error_envelope(brief_client: TestClient) -> None:
    response = brief_client.get("/api/v1/wards/not-a-ward/brief.pdf")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Unknown ward_id", "details": {}}
    }


def test_null_metrics_are_unavailable_and_suppressed_or_private_fields_are_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    cells_path = tmp_path / "cells.geojson"
    ward = _ward(
        gw_stage_pct=None,
        gw_category=None,
        beta_p90_horizon=None,
        beta_p90_ratio_horizon=None,
        vlm_median_mm_yr=None,
        score=None,
    )
    suppressed = _cell(
        "suppressed-cell-id",
        2,
        suppressed=True,
        cell_score=987654,
        beta_p90_horizon=876543,
        vlm_median_mm_yr=-999,
        building_id="building-PRIVATE-001",
        bldg_id="bldg-SECRET-002",
        authority_token="token-DO-NOT-PRINT",
    )
    cells_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": [suppressed]}),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"contract": "C2@1.0", "meta": {"data_vintage": "mock"}, "wards": [ward]}),
        encoding="utf-8",
    )
    store = APIData(
        DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )
    )
    monkeypatch.setattr(api_main, "data_store", store)
    response = TestClient(api_main.app).get("/api/v1/wards/ward-test-01/brief.pdf")
    text = _pdf_text(response)

    assert "Inspection Index Unavailable" in text
    assert "Groundwater stage of extraction Unavailable" in text
    assert "Median vertical land motion Unavailable" in text
    for secret in (
        "987654", "876543", "suppressed-cell-id", "building-PRIVATE-001",
        "bldg-SECRET-002", "token-DO-NOT-PRINT",
    ):
        assert secret not in text


def test_unsuppressed_cells_follow_c2_rank_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    cells_path = tmp_path / "cells.geojson"
    summary_path.write_text(
        json.dumps({"contract": "C2@1.0", "meta": {}, "wards": [_ward()]}),
        encoding="utf-8",
    )
    cells_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [
                _cell("cell-second", 2, bldg_id="building-private-001", authority_token="secret"),
                _cell("cell-first", 1),
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )),
    )
    text = _pdf_text(TestClient(api_main.app).get("/api/v1/wards/ward-test-01/brief.pdf"))

    assert text.index("cell-first") < text.index("cell-second")
    assert "building-private-001" not in text
    assert "secret" not in text


def test_unranked_eligible_cells_are_separate_from_c2_inspection_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    cells_path = tmp_path / "cells.geojson"
    summary_path.write_text(
        json.dumps({"contract": "C2@1.0", "meta": {}, "wards": [_ward()]}),
        encoding="utf-8",
    )
    cells_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [
                _cell("cell-unranked-b", None),
                _cell("cell-ranked", 1),
                _cell("cell-unranked-a", None),
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )),
    )
    text = _pdf_text(TestClient(api_main.app).get("/api/v1/wards/ward-test-01/brief.pdf"))

    ranked_section = text.index("Suggested inspection order")
    unranked_section = text.index("Eligible cells without a C2 rank (not ordered)")
    assert ranked_section < text.index("cell-ranked") < unranked_section
    assert unranked_section < text.index("cell-unranked-b")
    assert text.index("cell-unranked-b") < text.index("cell-unranked-a")
    assert "Unranked" in text


def test_long_ward_name_and_uncertainty_flag_wrap_without_losing_caveat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    cells_path = tmp_path / "cells.geojson"
    long_name = "North " + "Demonstration " * 24 + "Ward"
    long_flag = "boundary_vintage_" + "uncertainty_detail_" * 20
    summary_path.write_text(
        json.dumps({
            "contract": "C2@1.0",
            "meta": {"data_vintage": "2015-2023", "engine_version": "engine-test"},
            "wards": [_ward(ward_name=long_name, flags=[long_flag])],
        }),
        encoding="utf-8",
    )
    cells_path.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )),
    )
    response = TestClient(api_main.app).get("/api/v1/wards/ward-test-01/brief.pdf")
    text = _pdf_text(response)

    assert "Demonstration" in text and "Ward" in text
    assert "boundary_vintage_" in text
    assert "uncertainty_detail_" in text
    assert "ranks areas for inspection; does not certify any building; projections are scenarios under constant rates" in text


def test_large_cell_list_stays_one_page_and_reports_omissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    cells_path = tmp_path / "cells.geojson"
    summary_path.write_text(
        json.dumps({"contract": "C2@1.0", "meta": {}, "wards": [_ward()]}),
        encoding="utf-8",
    )
    cells_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [_cell(f"cell-{index:02d}", index + 1) for index in range(30)],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_main,
        "data_store",
        APIData(DataPaths(
            ward_summary=summary_path,
            cell_scores=cells_path,
            building_metrics=tmp_path / "unused.parquet",
            validation_summary=tmp_path / "unused-validation.json",
            buildings_geometry=None,
        )),
    )
    text = _pdf_text(TestClient(api_main.app).get("/api/v1/wards/ward-test-01/brief.pdf"))

    assert "23 additional eligible cell(s) omitted for space" in text
    assert "cell-06" in text
    assert "cell-07" not in text


def test_generation_failure_is_generic_and_does_not_leak_exception(
    brief_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("private-path-or-secret-token")

    monkeypatch.setattr(api_main, "generate_brief_pdf", fail)
    response = TestClient(api_main.app, raise_server_exceptions=False).get(
        "/api/v1/wards/ward-test-01/brief.pdf"
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal", "message": "Unexpected failure", "details": {}}
    }
    assert "private-path-or-secret-token" not in response.text


def test_brief_route_openapi_matches_c4(brief_client: TestClient) -> None:
    operation = brief_client.get("/api/v1/openapi.json").json()["paths"][
        "/api/v1/wards/{ward_id}/brief.pdf"
    ]["get"]
    assert set(operation["responses"]) == {"200", "404", "429", "500"}
    assert set(operation["responses"]["200"]["content"]) == {"application/pdf"}
    assert operation["responses"]["200"]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
