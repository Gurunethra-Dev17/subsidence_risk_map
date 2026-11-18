"""Serve an internal C5 tile candidate with Range, CORS, and cache headers."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

TILES_CANDIDATE_NAME = "TILES_CANDIDATE.json"

# Allowed CORS origins for the internal preview server (localhost only).
_LOCALHOST_RE = re.compile(
    r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$"
)

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _manifest_tile_path(candidate_dir: Path, filename: str) -> tuple[str, Path]:
    """Resolve a manifest tile and reject absolute or escaping paths."""
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Tile manifest paths must be relative")
    candidate_root = candidate_dir.resolve()
    target = (candidate_root / relative).resolve()
    if not target.is_relative_to(candidate_root):
        raise ValueError("Tile manifest path escapes candidate directory")
    if not target.is_file():
        raise FileNotFoundError(target)
    if relative.parts and relative.parts[0] == "authority":
        return "authority", target
    if not relative.parts or len(relative.parts) == 1 or relative.parts[0] == "public":
        return "public", target
    raise ValueError("Tile manifest files must be under public/ or authority/")


def _parse_byte_range(range_header: str | None, size: int) -> tuple[int, int] | bool | None:
    if not range_header:
        return None
    match = RANGE_RE.fullmatch(range_header.strip())
    if not match or "," in range_header:
        return False
    first, last = match.groups()
    if not first and not last:
        return False
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        suffix = int(last)
        start = max(0, size - suffix)
    if start >= size or end < start:
        return False
    return start, end


def _write_stream_chunks(stream: Any, wfile: Any, length: int) -> None:
    remaining = length
    while remaining:
        chunk = stream.read(min(64 * 1024, remaining))
        if not chunk:
            break
        wfile.write(chunk)
        remaining -= len(chunk)


def _load_manifest_and_dirs(candidate_dir: Path) -> tuple[Path, dict[str, Any], Path]:
    pmtiles_dir = candidate_dir / "pmtiles-wards-cells"
    candidate_manifest = candidate_dir / TILES_CANDIDATE_NAME
    if not (pmtiles_dir / TILES_CANDIDATE_NAME).is_file() and candidate_manifest.is_file():
        pmtiles_dir = candidate_dir
    fallback_dir = candidate_dir / "geojson"
    tile_manifest_path = pmtiles_dir / TILES_CANDIDATE_NAME
    if not tile_manifest_path.is_file():
        raise FileNotFoundError(tile_manifest_path)
    tile_manifest = json.loads(tile_manifest_path.read_text(encoding="utf-8"))
    return pmtiles_dir, tile_manifest, fallback_dir


def _index_tiles(pmtiles_dir: Path, files: list[dict[str, Any]]) -> tuple[dict[str, Path], dict[str, Path]]:
    public_tiles: dict[str, Path] = {}
    authority_tiles: dict[str, Path] = {}
    for item in files:
        access, tile_path = _manifest_tile_path(pmtiles_dir, item["file"])
        tile_names = public_tiles if access == "public" else authority_tiles
        tile_name = tile_path.name
        if tile_name in tile_names:
            raise ValueError(f"Duplicate {access} tile filename in manifest: {tile_name}")
        tile_names[tile_name] = tile_path
    return public_tiles, authority_tiles


def _index_geojson(fallback_dir: Path) -> dict[str, Path]:
    geojson_tiles: dict[str, Path] = {}
    if fallback_dir.is_dir():
        for entry in fallback_dir.iterdir():
            if entry.is_file() and entry.name.endswith(".json"):
                geojson_tiles[entry.name] = entry.resolve()
    return geojson_tiles


def _resolve_request_target(
    path: str,
    city: str,
    public_tiles: dict[str, Path],
    authority_tiles: dict[str, Path],
    geojson_tiles: dict[str, Path],
) -> tuple[Path | None, str | None, str | None]:
    parts = [unquote(part) for part in path.split("/") if part]
    if len(parts) == 2 and parts[0] == city and parts[1] in public_tiles:
        return public_tiles[parts[1]], "application/vnd.pmtiles", None
    if (
        len(parts) == 3
        and parts[0] == city
        and parts[1] == "authority"
        and parts[2] in authority_tiles
    ):
        return authority_tiles[parts[2]], "application/vnd.pmtiles", None
    if (
        len(parts) == 3
        and parts[0] == city
        and parts[1] == "geojson"
        and parts[2] in geojson_tiles
    ):
        return geojson_tiles[parts[2]], "application/geo+json", "gzip"
    return None, None, None


def make_handler(candidate_dir: Path):
    candidate_dir = candidate_dir.resolve()
    pmtiles_dir, tile_manifest, fallback_dir = _load_manifest_and_dirs(candidate_dir)
    city = tile_manifest["city"]
    public_tiles, authority_tiles = _index_tiles(pmtiles_dir, tile_manifest["files"])
    geojson_tiles = _index_geojson(fallback_dir)

    class TileHandler(BaseHTTPRequestHandler):
        server_version = "SubsidenceTilePreview/1.0"

        def _send_common(self, status: int, size: int = 0, content_type: str = "application/octet-stream"):
            self.send_response(status)
            origin = self.headers.get("Origin", "")
            if _LOCALHOST_RE.match(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Range")
            self.send_header("Access-Control-Expose-Headers", "Accept-Ranges, Content-Range, Content-Length")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", content_type)
            if size >= 0:
                self.send_header("Content-Length", str(size))

        def do_OPTIONS(self):
            self._send_common(204)
            self.end_headers()

        def do_HEAD(self):
            self._serve(head_only=True)

        def do_GET(self):
            self._serve(head_only=False)

        def _serve(self, *, head_only: bool):
            path = urlsplit(self.path).path
            target, content_type, content_encoding = _resolve_request_target(
                path, city, public_tiles, authority_tiles, geojson_tiles
            )
            if target is None or not target.is_file():
                body = b"not found\n"
                self._send_common(404, len(body), "text/plain; charset=utf-8")
                self.end_headers()
                if not head_only:
                    self.wfile.write(body)
                return

            size = target.stat().st_size
            parsed_range = _parse_byte_range(self.headers.get("Range"), size)
            if parsed_range is False:
                self._send_common(416, 0)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return

            start, end = (0, size - 1) if parsed_range is None else parsed_range
            status = 206 if parsed_range is not None else 200
            length = end - start + 1
            self._send_common(status, length, content_type or "application/octet-stream")
            if content_encoding:
                self.send_header("Content-Encoding", content_encoding)
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head_only:
                return
            with target.open("rb") as stream:
                stream.seek(start)
                _write_stream_chunks(stream, self.wfile, length)

        def log_message(self, format_string: str, *args):
            print(f"{self.address_string()} - {format_string % args}")

    return TileHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        host_address = ipaddress.ip_address(args.host)
    except ValueError:
        parser.error("The internal preview server host must be an IPv4 loopback IP")
    if host_address.version != 4 or not host_address.is_loopback:
        parser.error("The internal preview server must bind to an IPv4 loopback address")
    candidate_dir = args.candidate_dir.resolve()
    _pmtiles_dir, manifest, _ = _load_manifest_and_dirs(candidate_dir)
    city = manifest["city"]
    server = ThreadingHTTPServer((args.host, args.port), make_handler(candidate_dir))  # NOSONAR: local preview server
    print(f"Serving internal C5 candidate on loopback at {args.host}:{args.port}/{city}/")
    try:
        server.serve_forever()  # NOSONAR: local dev server intentionally binds cleartext loopback
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
