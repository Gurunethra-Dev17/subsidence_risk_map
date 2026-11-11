"""Validate committed contract fixtures using their JSON Schemas."""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "contracts" / "schemas"
MOCK = ROOT / "contracts" / "mock"


def validate(schema_name: str, fixture_name: str) -> list[str]:
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    instance = json.loads((MOCK / fixture_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [f"{error.json_path}: {error.message}" for error in validator.iter_errors(instance)]


def main() -> int:
    pairs = [
        ("pack_manifest.schema.json", "delhi-pack-0.0.1/PACK_MANIFEST.json"),
        ("building_metrics.schema.json", "building_metrics.json"),
        ("ward_summary.schema.json", "ward_summary.json"),
        ("cell_scores.schema.json", "cell_scores.geojson"),
        ("validation_summary.schema.json", "validation_summary.json"),
        ("config.schema.json", "config.json"),
    ]
    failures = 0
    for schema, fixture in pairs:
        issues = validate(schema, fixture)
        if issues:
            failures += len(issues)
            for issue in issues:
                print(f"FAIL {fixture}: {issue}")
        else:
            print(f"PASS {fixture}")
    if failures:
        print(f"{failures} contract validation error(s)")
        return 1
    print(f"Validated {len(pairs)} contract fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
