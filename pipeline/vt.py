"""Prepare Virginia Tech v2 VLM points and collapse incidents for C0."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


LOG = logging.getLogger("pipeline.vt")
XLSX_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
VLM_FILENAME = "vlm_points.parquet"
INCIDENTS_FILENAME = "collapse_incidents.csv"
VLM_SOURCE = "vt-in-v2"


def convert_vlm(input_path: Path, output_path: Path, city: str) -> dict[str, Any]:
    """Convert the selected city's VLM CSV from cm/year to mm/year, preserving rows."""
    import pandas as pd

    if not input_path.exists():
        raise FileNotFoundError(input_path)
    table = pd.read_csv(input_path)
    result = _vlm_table(table, city, pd)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False, compression="snappy")
    return {
        "rows": len(result),
        "longitude_range": [float(result.lon.min()), float(result.lon.max())],
        "latitude_range": [float(result.lat.min()), float(result.lat.max())],
        "vlm_mm_yr_range": [float(result.vlm_mm_yr.min()), float(result.vlm_mm_yr.max())],
        "repeated_coordinate_rows_preserved": True,
        "source": VLM_SOURCE,
    }


def _vlm_table(table: Any, city: str, pd: Any) -> Any:
    required = {"Longitude", "Latitude", "VLM_cm_per_yr"}
    missing = required - set(table.columns)
    if missing:
        raise ValueError(f"VLM CSV is missing columns: {', '.join(sorted(missing))}")
    lon = pd.to_numeric(table["Longitude"], errors="coerce")
    lat = pd.to_numeric(table["Latitude"], errors="coerce")
    vlm = pd.to_numeric(table["VLM_cm_per_yr"], errors="coerce")
    if lon.isna().any() or lat.isna().any() or vlm.isna().any():
        raise ValueError("VLM source contains null or nonnumeric values")
    result = pd.DataFrame(
        {
            "pt_id": [f"{VLM_SOURCE}:{city}:{i:06d}" for i in range(1, len(table) + 1)],
            "lon": lon.astype("float64"),
            "lat": lat.astype("float64"),
            "vlm_mm_yr": (vlm * 10).astype("float64"),
            "source": VLM_SOURCE,
        }
    )
    if not result["pt_id"].is_unique:
        raise ValueError("Generated VLM point IDs are not unique")
    return result


def _column_number(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if letters is None:
        raise ValueError(f"Invalid Excel cell reference: {reference}")
    result = 0
    for character in letters.group(0):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _read_first_worksheet(input_path: Path) -> list[tuple[int, list[str]]]:
    """Read the first worksheet with the standard library, avoiding an Excel dependency."""
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    with zipfile.ZipFile(input_path) as archive:
        names = set(archive.namelist())
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in names:
            raise ValueError("Incident workbook has no first worksheet XML")
        shared = _shared_strings(archive, names)
        sheet = ElementTree.fromstring(archive.read(sheet_name))
        return _worksheet_rows(sheet, shared)


def _shared_strings(archive: Any, names: set[str]) -> list[str]:
    shared_name = "xl/sharedStrings.xml"
    if shared_name not in names:
        return []
    shared_root = ElementTree.fromstring(archive.read(shared_name))
    return [
        "".join(node.text or "" for node in item.findall(".//m:t", XLSX_NS))
        for item in shared_root.findall("m:si", XLSX_NS)
    ]


def _cell_text(cell: Any, shared: list[str]) -> str:
    value = cell.find("m:v", XLSX_NS)
    text = value.text if value is not None and value.text is not None else ""
    if cell.attrib.get("t") == "s" and text:
        return shared[int(text)]
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", XLSX_NS))
    return text


def _worksheet_rows(sheet: Any, shared: list[str]) -> list[tuple[int, list[str]]]:
    rows = []
    for row in sheet.findall(".//m:sheetData/m:row", XLSX_NS):
        values = {
            _column_number(cell.attrib.get("r", "")): _cell_text(cell, shared)
            for cell in row.findall("m:c", XLSX_NS)
        }
        width = max(values, default=-1) + 1
        rows.append((int(row.attrib.get("r", "0")), [values.get(i, "") for i in range(width)]))
    return rows


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _date_iso(value: str) -> str | None:
    value = value.strip()
    if not value or value in {"-", "Unknown", "unknown", "Not reported"}:
        return None
    value = value[:-2] if value.endswith(".0") else value
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Unexpected incident date value: {value!r}") from exc


def convert_incidents(input_path: Path, output_path: Path, city: str) -> dict[str, Any]:
    """Filter incidents to the source city label; do not infer coordinates from addresses."""
    rows = _read_first_worksheet(input_path)
    if len(rows) < 2:
        raise ValueError("Incident workbook has no populated data rows")
    indices = _incident_columns(rows[0][1])

    output_rows = []
    source_count = 0
    for excel_row, values in rows[1:]:
        if not any(values):
            continue
        source_count += 1
        get = lambda name: _clean(values[indices[name]]) if indices[name] < len(values) else ""
        if get("City").casefold() != city.casefold():
            continue
        output_rows.append(_incident_record(excel_row, city, indices, get))

    if not output_rows:
        raise ValueError(f"No incidents with source City={city!r} were found")
    if len({row["incident_id"] for row in output_rows}) != len(output_rows):
        raise ValueError("Generated incident IDs are not unique")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["incident_id", "lon", "lat", "city", "date", "note"])
        writer.writeheader()
        writer.writerows(output_rows)
    return {
        "source_rows": source_count,
        "city_rows": len(output_rows),
        "null_coordinates": len(output_rows),
        "dates_null": sum(row["date"] is None for row in output_rows),
        "city": city.title(),
    }


def _incident_columns(headers: list[str]) -> dict[str, int]:
    indices = {header: index for index, header in enumerate(headers)}
    required = ["Date (YYYYMMMDD)", "Address", "Structure that collapsed", "City", "Injury", "Death"]
    missing = [name for name in required if name not in indices]
    if missing:
        raise ValueError(f"Incident workbook is missing columns: {', '.join(missing)}")
    return indices


def _incident_record(excel_row: int, city: str, indices: dict[str, int], get: Any) -> dict[str, Any]:
    note_fields = [
        ("Address", get("Address")),
        ("Structure", get("Structure that collapsed")),
        ("Injuries", get("Injury")),
        ("Deaths", get("Death")),
    ]
    note_fields.extend((field, get(field)) for field in ("Research paper", "Cited sources") if field in indices)
    note = "; ".join(f"{label}: {value}" for label, value in note_fields if value)
    return {
        "incident_id": f"{VLM_SOURCE}:incident:{excel_row:03d}",
        "lon": "",
        "lat": "",
        "city": city.title(),
        "date": _date_iso(get("Date (YYYYMMMDD)")),
        "note": note,
    }


def main() -> None:
    import yaml

    parser = argparse.ArgumentParser(description="Prepare Virginia Tech v2 C0 VLM and incident tables.")
    parser.add_argument("--config", type=Path, required=True, help="City C6 YAML config")
    parser.add_argument("--vlm", type=Path, required=True, help="Source VLM CSV")
    parser.add_argument("--incidents", type=Path, required=True, help="Source incident XLSX")
    parser.add_argument("--output-dir", type=Path, required=True, help="Working output directory under data/raw")
    args = parser.parse_args()
    with args.config.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if config.get("contract") != "C6@1.0":
        raise ValueError(f"Expected a C6@1.0 city config: {args.config}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    vlm = convert_vlm(args.vlm, args.output_dir / "vlm_points_delhi.parquet", config["city"])
    incidents = convert_incidents(args.incidents, args.output_dir / "collapse_incidents_delhi.csv", config["city"])
    LOG.info("VLM: %s", json.dumps(vlm, sort_keys=True))
    LOG.info("Incidents: %s", json.dumps(incidents, sort_keys=True))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
