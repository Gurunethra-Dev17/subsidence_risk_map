"""Assemble and validate a C0 pack from explicit input files."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from pipeline.manifest import REQUIRED_PACK_FILES, write_manifest
from pipeline.quality import validate_pack


def _parse_file(value: str) -> tuple[str, Path]:
    """Parse ``PACK_FILENAME=SOURCE_PATH`` without guessing file mappings."""
    name, separator, source = value.partition("=")
    if not separator or not name or not source:
        raise argparse.ArgumentTypeError("--file must be PACK_FILENAME=SOURCE_PATH")
    if Path(name).name != name or name not in REQUIRED_PACK_FILES:
        raise argparse.ArgumentTypeError(f"unsupported C0 pack filename: {name!r}")
    return name, Path(source)


def assemble_pack(
    pack_dir: Path,
    *,
    city: str,
    pack_version: str,
    files: dict[str, Path],
    sources: list[dict[str, str]],
    attribution: list[str],
    notes: list[str],
    expected_wards: int | None = None,
) -> dict[str, object]:
    """Stage, manifest, and quality-check a pack before publishing its directory.

    The destination must not exist. All six contract files and explicit source
    metadata are required so this helper cannot silently create a partial pack
    or invent provenance.
    """
    pack_dir = pack_dir.resolve()
    missing = sorted(REQUIRED_PACK_FILES - set(files))
    extra = sorted(set(files) - REQUIRED_PACK_FILES)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing mappings: {', '.join(missing)}")
        if extra:
            details.append(f"unsupported mappings: {', '.join(extra)}")
        raise ValueError("Invalid C0 input mapping (" + "; ".join(details) + ")")
    if not sources:
        raise ValueError("C0 manifest needs at least one source with licence and access date")
    if pack_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing pack directory: {pack_dir}")

    resolved_files: dict[str, Path] = {}
    for name, path in files.items():
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Input for {name} is not a file: {resolved}")
        resolved_files[name] = resolved

    pack_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{pack_dir.name}-", dir=pack_dir.parent) as temp_name:
        staged = Path(temp_name) / pack_dir.name
        staged.mkdir()
        for name, source_path in resolved_files.items():
            shutil.copyfile(source_path, staged / name)

        write_manifest(
            staged,
            city=city,
            pack_version=pack_version,
            sources=sources,
            attribution=attribution,
            notes=notes,
        )
        report = validate_pack(staged, expected_wards=expected_wards)
        if report["errors"]:
            rendered = json.dumps(report, indent=2, ensure_ascii=False)
            raise ValueError(f"Staged C0 pack failed quality checks:\n{rendered}")

        # The staged directory shares a volume with the destination, so this
        # rename publishes the validated pack as one filesystem operation.
        staged.replace(pack_dir)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble, manifest, and validate all six files in a C0 pack."
    )
    parser.add_argument("pack_dir", type=Path)
    parser.add_argument("--city", required=True)
    parser.add_argument("--version", required=True, dest="pack_version")
    parser.add_argument(
        "--file", action="append", default=[], type=_parse_file,
        metavar="PACK_FILENAME=SOURCE_PATH",
    )
    parser.add_argument("--source", action="append", default=[], metavar="NAME|URL|LICENCE|ACCESSED_UTC")
    parser.add_argument("--attribution", action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--expected-wards", type=int)
    args = parser.parse_args()

    files: dict[str, Path] = {}
    for name, path in args.file:
        if name in files:
            parser.error(f"--file maps {name!r} more than once")
        files[name] = path

    sources = []
    for value in args.source:
        parts = value.split("|", maxsplit=3)
        if len(parts) != 4 or not all(parts):
            parser.error("--source must be NAME|URL|LICENCE|ACCESSED_UTC")
        sources.append(dict(zip(("name", "url", "licence", "accessed_utc"), parts, strict=True)))

    report = assemble_pack(
        args.pack_dir,
        city=args.city,
        pack_version=args.pack_version,
        files=files,
        sources=sources,
        attribution=args.attribution,
        notes=args.note,
        expected_wards=args.expected_wards,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
