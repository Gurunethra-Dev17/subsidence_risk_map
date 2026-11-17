"""Helpers for keeping generated files inside their configured data directory."""

from __future__ import annotations

from pathlib import Path


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
