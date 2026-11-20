"""Read the frozen C1, C2, and C3 artefacts for API endpoint handlers.

E3 can use the module-level ``data_store`` or construct ``APIData`` with
alternate fixture paths for tests and deployments. JSON artefacts are read
from disk when their modification time or size changes. C1 metrics are queried
directly from Parquet through DuckDB.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MOCK_ROOT = _REPO_ROOT / "contracts" / "mock"
_CELL_METRICS = (
    "vlm_median_mm_yr",
    "beta_p90_horizon",
    "share_sinking_gt4",
    "cell_score",
    "cell_rank_in_ward",
)
_BUILDING_PROPERTIES = (
    "bldg_id",
    "vlm_mm_yr",
    "beta_ratio_horizon",
    "beta_class",
    "sparse",
)


def _configured_path(env_name: str, mock_default: Path) -> Path | None:
    """Use mock artifacts only for explicit dev mode; never infer a fallback."""
    configured = os.getenv(env_name)
    is_dev = os.getenv("API_ENV", "").casefold() == "dev"
    if configured is None:
        return mock_default if is_dev else None
    if not configured.strip():
        return None

    path = Path(configured).expanduser()
    if not is_dev:
        try:
            if path.resolve().is_relative_to(_MOCK_ROOT.resolve()):
                return None
        except (OSError, RuntimeError):
            pass
    return path


def _configured_optional_path(env_name: str) -> Path | None:
    configured = os.getenv(env_name)
    return Path(configured).expanduser() if configured else None


@dataclass(frozen=True)
class DataPaths:
    """Configurable locations for the API's contract artefacts."""

    ward_summary: Path | None = field(
        default_factory=lambda: _configured_path(
            "API_WARD_SUMMARY_PATH", _MOCK_ROOT / "ward_summary.json"
        )
    )
    cell_scores: Path | None = field(
        default_factory=lambda: _configured_path(
            "API_CELL_SCORES_PATH", _MOCK_ROOT / "cell_scores.geojson"
        )
    )
    building_metrics: Path | None = field(
        default_factory=lambda: _configured_path(
            "API_BUILDING_METRICS_PATH", _MOCK_ROOT / "building_metrics.parquet"
        )
    )
    validation_summary: Path | None = field(
        default_factory=lambda: _configured_path(
            "API_VALIDATION_SUMMARY_PATH", _MOCK_ROOT / "validation_summary.json"
        )
    )
    buildings_geometry: Path | None = field(
        default_factory=lambda: _configured_optional_path(
            "API_BUILDINGS_GEOMETRY_PATH"
        )
    )


@lru_cache(maxsize=32)
def _load_json_cached(path: str, mtime_ns: int, size: int) -> Any:
    """Cache parsed JSON by file identity and modification signature."""
    del mtime_ns, size  # Cache-key inputs; stat changes invalidate the entry.
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_json(path: str | Path | None) -> Any:
    """Load JSON, reusing the parsed value until the source file changes."""
    if path is None:
        raise FileNotFoundError("API artifact path is not configured")
    source = Path(path).expanduser().resolve()
    stat = source.stat()
    return deepcopy(_load_json_cached(str(source), stat.st_mtime_ns, stat.st_size))


def json_etag(data: Any) -> str:
    """Return a quoted, deterministic SHA-256 ETag for JSON-compatible data."""
    canonical = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f'"{hashlib.sha256(canonical).hexdigest()}"'


def parse_bbox(
    bbox: str | Sequence[float] | None,
) -> tuple[float, float, float, float] | None:
    """Parse and validate bbox as minLon,minLat,maxLon,maxLat (EPSG:4326)."""
    if bbox is None:
        return None
    try:
        values = bbox.split(",") if isinstance(bbox, str) else list(bbox)
        if len(values) != 4:
            raise ValueError
        min_lon, min_lat, max_lon, max_lat = (float(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("bbox must have 4 numbers") from exc

    if not all(math.isfinite(value) for value in (min_lon, min_lat, max_lon, max_lat)):
        raise ValueError("bbox coordinates must be finite numbers")
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise ValueError("bbox longitude must be between -180 and 180")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise ValueError("bbox latitude must be between -90 and 90")
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("bbox minimum coordinates must not exceed maximum coordinates")
    return min_lon, min_lat, max_lon, max_lat


class SpatialDataUnavailableError(RuntimeError):
    """Raised when a requested bbox cannot be evaluated from available columns."""


class APIData:
    """Contract-aware access to ward, cell, and building artefacts."""

    def __init__(self, paths: DataPaths | None = None) -> None:
        self.paths = paths or DataPaths()

    def load_ward_summary(self) -> dict[str, Any]:
        """Load the C2 ward summary document."""
        return load_json(self.paths.ward_summary)

    def list_wards(
        self,
        *,
        status: Literal["ranked", "insufficient_data"] | None = None,
        sort: Literal["rank", "score", "name"] = "rank",
        order: Literal["asc", "desc"] = "asc",
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Filter, sort, and paginate C2 ward summaries in the C4 envelope."""
        if status not in (None, "ranked", "insufficient_data"):
            raise ValueError("status must be ranked or insufficient_data")
        if sort not in ("rank", "score", "name"):
            raise ValueError("sort must be rank, score, or name")
        if order not in ("asc", "desc"):
            raise ValueError("order must be asc or desc")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= 500:
            raise ValueError("limit must be between 0 and 500")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be a non-negative integer")

        wards = self.load_ward_summary().get("wards", [])
        if status is not None:
            wards = [ward for ward in wards if ward.get("status") == status]
        if q:
            query = q.casefold()
            wards = [ward for ward in wards if query in ward.get("ward_name", "").casefold()]

        if sort == "name":
            wards.sort(key=lambda ward: (ward.get("ward_name", "").casefold(), ward["ward_id"]))
            if order == "desc":
                wards.reverse()
        else:
            field = sort
            present = [ward for ward in wards if ward.get(field) is not None]
            missing = [ward for ward in wards if ward.get(field) is None]
            present.sort(key=lambda ward: (ward[field], ward["ward_id"]), reverse=order == "desc")
            wards = present + missing

        total = len(wards)
        return {
            "items": wards[offset : offset + limit],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_ward(self, ward_id: str) -> dict[str, Any] | None:
        """Return one C2 ward object, or ``None`` when its ID is unknown."""
        return next(
            (ward for ward in self.load_ward_summary().get("wards", [])
             if ward.get("ward_id") == ward_id),
            None,
        )

    def load_cell_scores(self) -> dict[str, Any]:
        """Load the C2 GeoJSON FeatureCollection."""
        return load_json(self.paths.cell_scores)

    def load_validation_summary(self) -> dict[str, Any]:
        """Load the C3 validation summary document."""
        return load_json(self.paths.validation_summary)

    def get_cells(self, ward_id: str) -> dict[str, Any]:
        """Return a ward's cells, preserving the FeatureCollection and hiding suppressed metrics."""
        collection = self.load_cell_scores()
        features = []
        for feature in collection.get("features", []):
            properties = feature.get("properties", {})
            if properties.get("ward_id") != ward_id:
                continue
            if properties.get("suppressed") is True:
                feature["properties"] = dict(properties)
                for field in _CELL_METRICS:
                    feature["properties"][field] = None
            features.append(feature)
        collection["features"] = features
        return collection

    def get_buildings(
        self,
        *,
        ward_id: str | None = None,
        bbox: str | Sequence[float] | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Query C1 metrics and optional C0 geometry into the C4 GeoJSON shape.

        When C0 geometry is configured, C0 is the left side of the join so
        buildings without C1 metrics remain present with null metric values.
        Bbox filtering then uses true polygon intersection in EPSG:4326.
        Without C0, the original C1-only coordinate filtering remains active.
        """
        parsed_bbox = parse_bbox(bbox)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= 5000:
            raise ValueError("limit must be between 0 and 5000")
        if self.paths.building_metrics is None:
            raise FileNotFoundError("C1 building metrics path is not configured")
        source = Path(self.paths.building_metrics).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"C1 Parquet fixture not found: {source}")

        geometry_source = None
        if self.paths.buildings_geometry is not None:
            geometry_source = Path(self.paths.buildings_geometry).expanduser().resolve()
            if not geometry_source.is_file():
                raise FileNotFoundError(
                    f"C0 building geometry Parquet not found: {geometry_source}"
                )

        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - depends on API install extra
            raise RuntimeError("DuckDB is required to read C1 Parquet data") from exc

        with duckdb.connect(database=":memory:") as connection:
            if geometry_source is not None:
                connection.execute("LOAD spatial")
                c0_description = connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)", [str(geometry_source)]
                ).fetchall()
                c0_columns = {row[0].casefold() for row in c0_description}
                required_c0 = {"bldg_id", "ward_id", "cell_id", "geometry"}
                missing_c0 = required_c0 - c0_columns
                if missing_c0:
                    raise ValueError(
                        "C0 Parquet is missing columns: "
                        f"{', '.join(sorted(missing_c0))}"
                    )
                geometry_type = next(
                    row[1] for row in c0_description if row[0].casefold() == "geometry"
                ).upper()
                if geometry_type.startswith("GEOMETRY"):
                    geometry_expression = 'c0."geometry"'
                elif geometry_type == "BLOB":
                    geometry_expression = 'ST_GeomFromWKB(c0."geometry")'
                else:
                    raise ValueError(
                        "C0 geometry column must be DuckDB GEOMETRY or WKB BLOB; "
                        f"got {geometry_type}"
                    )
                c1_description = connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)", [str(source)]
                ).fetchall()
                c1_columns = {row[0].casefold() for row in c1_description}
                missing_c1 = set(_BUILDING_PROPERTIES) - c1_columns
                if missing_c1:
                    raise ValueError(
                        "C1 Parquet is missing columns: "
                        f"{', '.join(sorted(missing_c1))}"
                    )

                query = (
                    'SELECT c0."bldg_id" AS bldg_id, '
                    + ", ".join(
                        f'c1."{column}" AS "{column}"'
                        for column in _BUILDING_PROPERTIES[1:]
                    )
                    + f", ST_AsGeoJSON({geometry_expression}) AS __geometry "
                    + "FROM read_parquet(?) AS c0 "
                    + 'LEFT JOIN read_parquet(?) AS c1 ON c0."bldg_id" = c1."bldg_id"'
                )
                parameters: list[Any] = [str(geometry_source), str(source)]
                predicates: list[str] = []
                if ward_id is not None:
                    predicates.append('c0."ward_id" = ?')
                    parameters.append(ward_id)
                if parsed_bbox is not None:
                    predicates.append(
                        "ST_Intersects("
                        f"{geometry_expression}, "
                        "ST_MakeEnvelope(?, ?, ?, ?))"
                    )
                    parameters.extend(parsed_bbox)
                if predicates:
                    query += " WHERE " + " AND ".join(predicates)
                query += " LIMIT ?"
                parameters.append(limit)
                rows = connection.execute(query, parameters).fetchall()
                result_columns = [column[0] for column in connection.description]
            else:
                description = connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)", [str(source)]
                ).fetchall()
                columns = {row[0].casefold() for row in description}
                coordinate_columns = next(
                    (
                        pair for pair in (("lon", "lat"), ("longitude", "latitude"))
                        if set(pair).issubset(columns)
                    ),
                    None,
                )
                if parsed_bbox is not None and coordinate_columns is None:
                    raise SpatialDataUnavailableError(
                        "C1 Parquet has no explicit longitude/latitude columns; "
                        "bbox filtering requires location data joined by bldg_id"
                    )

                missing = set(_BUILDING_PROPERTIES) - columns
                if missing:
                    raise ValueError(
                        f"C1 Parquet is missing columns: {', '.join(sorted(missing))}"
                    )

                selected = list(_BUILDING_PROPERTIES)
                if coordinate_columns:
                    lon_column, lat_column = coordinate_columns
                    selected.extend(
                        (f'"{lon_column}" AS __lon', f'"{lat_column}" AS __lat')
                    )
                query = "SELECT " + ", ".join(selected) + " FROM read_parquet(?)"
                parameters = [str(source)]
                predicates = []
                if ward_id is not None:
                    predicates.append('"ward_id" = ?')
                    parameters.append(ward_id)
                if parsed_bbox is not None:
                    min_lon, min_lat, max_lon, max_lat = parsed_bbox
                    lon_column, lat_column = coordinate_columns or ("", "")
                    predicates.extend(
                        (
                            f'"{lon_column}" BETWEEN ? AND ?',
                            f'"{lat_column}" BETWEEN ? AND ?',
                        )
                    )
                    parameters.extend((min_lon, max_lon, min_lat, max_lat))
                if predicates:
                    query += " WHERE " + " AND ".join(predicates)
                query += " LIMIT ?"
                parameters.append(limit)
                rows = connection.execute(query, parameters).fetchall()
                result_columns = [column[0] for column in connection.description]

        features = []
        for row in rows:
            values = dict(zip(result_columns, row))
            properties = {key: values.get(key) for key in _BUILDING_PROPERTIES}
            geometry = None
            if "__geometry" in values and values["__geometry"] is not None:
                geometry = json.loads(values["__geometry"])
            elif (
                "__lon" in values
                and values["__lon"] is not None
                and values["__lat"] is not None
            ):
                geometry = {
                    "type": "Point",
                    "coordinates": [values["__lon"], values["__lat"]],
                }
            features.append({"type": "Feature", "geometry": geometry, "properties": properties})
        return {"type": "FeatureCollection", "features": features}


data_store = APIData()
