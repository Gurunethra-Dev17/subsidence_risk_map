"""Helpers for keeping generated files inside their configured data directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def pack_destination(pack_dir: Path, requested: Path | None, filename: str) -> Path:
    """Resolve an output path and reject paths that escape the configured pack."""
    root = pack_dir.resolve()
    candidate_path = requested if requested is not None else Path(filename)
    if not candidate_path.is_absolute():
        candidate_path = root / candidate_path
    candidate = candidate_path.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Output path must stay inside configured pack directory: {root}") from exc
    return candidate


def load_c6_config(config_path: Path) -> tuple[Path, dict[str, Any]]:
    """Load a C6 YAML config only from the project's configs directory."""
    import yaml

    project_root = Path(__file__).resolve().parents[1]
    config_root = (project_root / "configs").resolve()
    safe_config_path = config_path.resolve()
    try:
        relative_config = safe_config_path.relative_to(config_root)
    except ValueError as exc:
        raise ValueError(f"C6 config must be inside {config_root}") from exc
    if len(relative_config.parts) != 1 or safe_config_path.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("C6 config must be a YAML file directly inside configs/")
    with safe_config_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if config.get("contract") != "C6@1.0":
        raise ValueError(f"Expected a C6@1.0 city config: {safe_config_path}")
    return project_root, config


def resolve_pack_dir(project_root: Path, configured_path: str | Path) -> Path:
    """Resolve a relative C6 pack path inside the project; allow explicit absolute storage."""
    configured_pack = Path(configured_path)
    if configured_pack.is_absolute():
        return configured_pack.resolve()
    pack_dir = (project_root / configured_pack).resolve()
    try:
        pack_dir.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError("Relative pack_dir must stay inside the project directory") from exc
    return pack_dir
