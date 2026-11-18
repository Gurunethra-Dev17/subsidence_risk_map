"""Regression tests for the C5 candidate validator."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from pipeline.tile_quality import validate_candidate
from pipeline.tiles import C5_ATTRIBUTION


class TileQualityTests(unittest.TestCase):
    def _candidate(self, root: Path) -> Path:
        candidate = root / "candidate"
        candidate.mkdir()
        files = []
        fixtures = {
            "wards": ("wards.pmtiles", 2, ["ward_id", "ward_name", "status", "score", "rank"], "ward_id"),
            "cells": ("cells.pmtiles", 3, ["cell_id", "ward_id", "suppressed", "cell_score", "cell_rank_in_ward"], "cell_id"),
        }
        for layer, (filename, count, fields, id_field) in fixtures.items():
            archive = candidate / filename
            archive.write_bytes((layer + " archive").encode())
            files.append({
                "layer": layer,
                "file": filename,
                "minzoom": 0 if layer == "wards" else 8,
                "maxzoom": 12 if layer == "wards" else 14,
                "features": count,
                "bytes": archive.stat().st_size,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            })
        (candidate / "TILES_CANDIDATE.json").write_text(json.dumps({
            "contract": "C5@1.0",
            "city": "delhi",
            "kind": "geometry-only PMTiles candidate",
            "attribution": C5_ATTRIBUTION,
            "omitted_layers": ["points", "buildings"],
            "files": files,
        }), encoding="utf-8")
        return candidate

    def test_passes_with_clipped_tile_copies_and_distinct_source_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            candidate = self._candidate(Path(temp))

            def read_info(path, layer, **kwargs):
                fields = ("ward_id", "ward_name", "status", "score", "rank") if layer == "wards" else (
                    "cell_id", "ward_id", "suppressed", "cell_score", "cell_rank_in_ward"
                )
                return {"fields": fields, "features": 7, "crs": "EPSG:3857", "geometry_type": "MultiPolygon"}

            def read_dataframe(path, layer, columns):
                key = columns[0]
                values = ["a", "a", "b"] if layer == "wards" else ["a", "a", "b", "c"]
                return pd.DataFrame({key: values})

            fake = SimpleNamespace(read_info=read_info, read_dataframe=read_dataframe)
            with patch.dict("sys.modules", {"pyogrio": fake}):
                report = validate_candidate(candidate)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["layers"][0]["features"], 7)
            self.assertEqual(report["layers"][0]["unique_source_features"], 2)

    def test_detects_archive_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            candidate = self._candidate(Path(temp))
            archive = candidate / "wards.pmtiles"
            archive.write_bytes(b"changed")
            fake = SimpleNamespace()
            with patch.dict("sys.modules", {"pyogrio": fake}):
                report = validate_candidate(candidate)
            self.assertFalse(report["passed"])
            self.assertTrue(any("SHA-256" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
