"""Serve an internal C5 tile candidate with Range, CORS, and cache headers."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

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


def make_handler(candidate_dir: Path):
    candidate_dir = candidate_dir.resolve()
    # Accept either the shared tiles-candidate root (legacy layout) or a
    # versioned PMTiles candidate directory containing its own manifest.
    pmtiles_dir = candidate_dir / "pmtiles-wards-cells"
    candidate_manifest = candidate_dir / "TILES_CANDIDATE.json"
    if not (pmtiles_dir / "TILES_CANDIDATE.json").is_file() and candidate_manifest.is_file():
        pmtiles_dir = candidate_dir
    fallback_dir = candidate_dir / "geojson"
    geojson_tiles: dict[str, Path] = {}
    if fallback_dir.is_dir():
        for entry in fallback_dir.iterdir():
            if entry.is_file() and entry.name.endswith(".json"):
                geojson_tiles[entry.name] = entry.resolve()
    tile_manifest_path = pmtiles_dir / "TILES_CANDIDATE.json"
    if not tile_manifest_path.is_file():
        raise FileNotFoundError(tile_manifest_path)
    tile_manifest = json.loads(tile_manifest_path.read_text(encoding="utf-8"))
    city = tile_manifest["city"]
    public_tiles: dict[str, Path] = {}
    authority_tiles: dict[str, Path] = {}
    for item in tile_manifest["files"]:
        access, tile_path = _manifest_tile_path(pmtiles_dir, item["file"])
        tile_names = public_tiles if access == "public" else authority_tiles
        tile_name = tile_path.name
        if tile_name in tile_names:
            raise ValueError(f"Duplicate {access} tile filename in manifest: {tile_name}")
        tile_names[tile_name] = tile_path

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

        def _resolve(self, path: str):
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

        def _serve(self, *, head_only: bool):
            path = urlsplit(self.path).path
            target, content_type, content_encoding = self._resolve(path)
            if target is None or not target.is_file():
                body = b"not found\n"
                self._send_common(404, len(body), "text/plain; charset=utf-8")
                self.end_headers()
                if not head_only:
                    self.wfile.write(body)
                return

            size = target.stat().st_size
            start, end = 0, size - 1
            status = 200
            range_header = self.headers.get("Range")
            if range_header:
                match = RANGE_RE.fullmatch(range_header.strip())
                if not match or "," in range_header:
                    self._send_common(416, 0)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                first, last = match.groups()
                if not first and not last:
                    self._send_common(416, 0)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:
                    suffix = int(last)
                    start = max(0, size - suffix)
                if start >= size or end < start:
                    self._send_common(416, 0)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206

            length = end - start + 1
            self._send_common(status, length, content_type)
            if content_encoding:
                self.send_header("Content-Encoding", content_encoding)
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head_only:
                return
            with target.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining:
                    chunk = stream.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

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
    pmtiles_dir = candidate_dir / "pmtiles-wards-cells"
    candidate_manifest = candidate_dir / "TILES_CANDIDATE.json"
    if not (pmtiles_dir / "TILES_CANDIDATE.json").is_file() and candidate_manifest.is_file():
        pmtiles_dir = candidate_dir
    manifest = json.loads((pmtiles_dir / "TILES_CANDIDATE.json").read_text(encoding="utf-8"))
    city = manifest["city"]
    server = ThreadingHTTPServer((args.host, args.port), make_handler(candidate_dir))
    print(f"Serving internal C5 candidate at http://{args.host}:{args.port}/{city}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
