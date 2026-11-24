"""Validation and assembly helpers for the public C4 metadata endpoint."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

CONTRACT_VERSIONS = {
    "C0": "1.0",
    "C1": "1.0",
    "C2": "1.0",
    "C3": "1.0",
    "C4": "1.0",
    "C5": "1.0",
    "C6": "1.0",
}

_REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS_DIR = _REPO_ROOT / "configs"
SCHEMAS_DIR = _REPO_ROOT / "contracts" / "schemas"
_MOCK_ROOT = _REPO_ROOT / "contracts" / "mock"
_CITY_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]*\Z")


class MetadataValidationError(ValueError):
    """Raised when loaded C2 metadata or its city configuration is inconsistent."""


def _validate(document: Any, schema_name: str) -> None:
    schema_path = SCHEMAS_DIR / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(document)


def load_city_config(city: Any, c6_config_path: str | Path | None = None) -> dict[str, Any]:
    """Load a validated C6 config, optionally from an explicit deployment path."""
    if not isinstance(city, str) or not _CITY_IDENTIFIER.fullmatch(city):
        raise MetadataValidationError("Invalid city identifier")

    if c6_config_path is None:
        root = CONFIGS_DIR.resolve()
        path = (root / f"{city}.yaml").resolve(strict=True)
        if not path.is_relative_to(root):
            raise MetadataValidationError("Invalid city configuration path")
    else:
        path = Path(c6_config_path).expanduser().resolve(strict=True)
        if path.is_relative_to(_MOCK_ROOT.resolve()):
            raise MetadataValidationError("Invalid city configuration path")

    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    _validate(config, "config.schema.json")
    expected_contract = f"C6@{CONTRACT_VERSIONS['C6']}"
    if config.get("contract") != expected_contract or config.get("city") != city:
        raise MetadataValidationError("Inconsistent city configuration")
    if config.get("mode") not in {"public", "authority"}:
        raise MetadataValidationError("Invalid city mode")
    return config


def build_meta_payload(
    ward_summary: Any, *, c6_config_path: str | Path | None = None
) -> dict[str, Any]:
    """Validate C2 and its selected C6 config, then build the exact C4 payload."""
    _validate(ward_summary, "ward_summary.schema.json")
    expected_contract = f"C2@{CONTRACT_VERSIONS['C2']}"
    if ward_summary.get("contract") != expected_contract:
        raise MetadataValidationError("Unexpected C2 contract version")

    c2_meta = ward_summary["meta"]
    config = load_city_config(c2_meta["city"], c6_config_path)
    return {
        "city": c2_meta["city"],
        "data_vintage": c2_meta["data_vintage"],
        "generated_utc": c2_meta["generated_utc"],
        "engine_version": c2_meta["engine_version"],
        "params": c2_meta["params"],
        "weights": c2_meta["weights"],
        "n_wards": c2_meta["n_wards"],
        "n_ranked": c2_meta["n_ranked"],
        "default_mode": config["mode"],
        "contract_versions": dict(CONTRACT_VERSIONS),
    }
