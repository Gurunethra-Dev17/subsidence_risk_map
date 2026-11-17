"""Run deterministic C1 sensitivity experiments for C6 radius and pair windows."""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from engine.assign import assign_points_to_buildings
from engine.distortion import compute_building_distortion
from engine.export import export_building_metrics


class RobustnessError(ValueError):
    """Raised when robustness variants are missing or invalid."""


def _variants(cfg):
    try:
        radii = [float(value) for value in cfg.params["radius_variants_m"]]
        windows = cfg.params.get("pair_distance_variants_m")
        if windows is None:
            low = float(cfg.params["pair_min_m"])
            high = float(cfg.params["pair_max_m"])
            midpoint = (low + high) / 2
            windows = [[low, midpoint], [low, high], [midpoint, high]]
        windows = [[float(low), float(high)] for low, high in windows]
    except (KeyError, TypeError, ValueError) as exc:
        raise RobustnessError(
            "C6 params must define radius_variants_m and valid pair-distance variants"
        ) from exc
    if not radii or any(not math.isfinite(value) or value <= 0 for value in radii):
        raise RobustnessError("radius_variants_m must contain positive finite values")
    if len(set(radii)) != len(radii):
        raise RobustnessError("radius_variants_m values must be unique")
    if not windows:
        raise RobustnessError("pair_distance_variants_m must contain at least one window")
    for window in windows:
        if (len(window) != 2 or not all(math.isfinite(value) for value in window)
                or window[0] <= 0 or window[1] < window[0]):
            raise RobustnessError("pair-distance variants must satisfy 0 < min_m <= max_m")
    normalized_windows = [tuple(window) for window in windows]
    if len(set(normalized_windows)) != len(normalized_windows):
        raise RobustnessError("pair-distance variants must be unique")
    return radii, normalized_windows


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=f".{path.name}.",
            suffix=".tmp", dir=path.parent, delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
        raise


def run_robustness(buildings, points, cfg, output_dir: str | Path, *, engine_version: str) -> dict:
    """Export C1 results for every configured radius and pair-distance window.

    Assignment calculations are shared across pair windows at the same radius;
    distortion calculations are shared across radii for the same pair window.
    Each experiment is written under ``radius-XXXm/pairs-XXX-YYYm/`` with its
    own C1 Parquet file. A stable ``robustness_summary.json`` records parameters,
    output locations, config hashes, and VLM coverage for every experiment.
    """
    if not hasattr(cfg, "params") or not hasattr(cfg, "seed"):
        raise RobustnessError("cfg must be a parsed C6 Config")
    radii, windows = _variants(cfg)
    destination = Path(output_dir).resolve()

    assignments_by_radius = {}
    for radius in radii:
        params = {**cfg.params, "radius_m": radius}
        variant_cfg = replace(cfg, params=params)
        assignments_by_radius[radius] = assign_points_to_buildings(
            buildings, points, variant_cfg,
        )

    distortions_by_window = {}
    for pair_min_m, pair_max_m in windows:
        params = {
            **cfg.params,
            "pair_min_m": pair_min_m,
            "pair_max_m": pair_max_m,
        }
        variant_cfg = replace(cfg, params=params)
        distortions_by_window[(pair_min_m, pair_max_m)] = compute_building_distortion(
            buildings, points, variant_cfg,
        )

    experiments = []
    for radius in radii:
        for pair_min_m, pair_max_m in windows:
            params = {
                **cfg.params,
                "radius_m": radius,
                "pair_min_m": pair_min_m,
                "pair_max_m": pair_max_m,
            }
            variant_cfg = replace(cfg, params=params)
            radius_label = f"{radius:g}".replace(".", "p")
            pair_min_label = f"{pair_min_m:g}".replace(".", "p")
            pair_max_label = f"{pair_max_m:g}".replace(".", "p")
            relative_path = Path(
                f"radius-{radius_label}m"
            ) / f"pairs-{pair_min_label}-{pair_max_label}m" / "building_metrics.parquet"
            export = export_building_metrics(
                buildings,
                assignments_by_radius[radius],
                distortions_by_window[(pair_min_m, pair_max_m)],
                variant_cfg,
                destination / relative_path,
                engine_version=engine_version,
            )
            experiments.append({
                "radius_m": radius,
                "pair_min_m": pair_min_m,
                "pair_max_m": pair_max_m,
                "output": relative_path.as_posix(),
                "rows": export["rows"],
                "non_null_vlm_share": export["non_null_vlm_share"],
                "params_hash": export["params_hash"],
            })

    summary = {
        "contract": "C1@1.0",
        "city": cfg.city,
        "engine_version": engine_version,
        "seed": int(cfg.seed),
        "experiment_count": len(experiments),
        "experiments": experiments,
    }
    _write_json_atomic(destination / "robustness_summary.json", summary)
    return summary
