"""Serve approved C0/C5 geography and optional internal E7 artifacts on IPv4 loopback."""

import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.serve_tiles import _parse_byte_range, _write_stream_chunks

HOST = "127.0.0.1"
PORT = 8003
ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173"}
E7_FILES = {
    "overlay_manifest.json": (
        "application/json", "8bbbf1824ad3455044edb3ee951af95cafe2a0996b4ead3cdc8bcc8900498fee"
    ),
    "los_overlay.png": (
        "image/png", "20434023bc7de664608746a99a1bfe30b213d3f95e15b7e197c4f623d352f94e"
    ),
}


def approved_assets(root):
    checksums = {}
    for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split(maxsplit=1)
        checksums[name] = digest

    def verified(name):
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("Geography asset is outside its package.")
        with path.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != checksums.get(name):
                raise ValueError("Geography package integrity check failed.")
        return path

    manifest = json.loads(verified("c0/PACK_MANIFEST.json").read_text(encoding="utf-8"))
    wards = "c0/wards.geojson"
    if (manifest["city"], manifest["crs_storage"], manifest["pack_version"]) != (
        "delhi", "EPSG:4326", "delhi-candidate-0.0.1"
    ) or not any(entry["name"] == "wards.geojson" and entry["sha256"] == checksums[wards]
                 for entry in manifest["files"]):
        raise ValueError("The C0 manifest does not match the Delhi preview.")
    assets = {"/delhi/wards.geojson": (verified(wards), "application/geo+json", None)}
    tiles = json.loads(verified("c5/pmtiles/TILES_CANDIDATE.json").read_text(encoding="utf-8"))
    if tiles["city"] != "delhi":
        raise ValueError("The C5 manifest is for a different city.")
    for entry in tiles["files"]:
        if entry["layer"] not in {"wards", "cells", "points"}:
            continue
        filename = Path(entry["file"]).name
        name = "c5/pmtiles/" + filename
        if checksums.get(name) != entry["sha256"]:
            raise ValueError("C5 checksum declarations disagree.")
        assets["/delhi/" + filename] = (verified(name), "application/vnd.pmtiles", None)
    for ward_id in range(1, 251):
        name = str(ward_id) + ".json"
        file = verified("c5/ward-geojson-fallback/" + name)
        assets["/delhi/geojson/" + name] = (file, "application/geo+json", "gzip")
    return assets


def approved_e7_assets(directory):
    candidate = Path(directory)
    if not candidate.is_absolute():
        raise ValueError("Set DELHI_E7_DIR to the absolute outer E7 package directory.")
    root = candidate.resolve(strict=True)
    if root.is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("The E7 package must live outside the repository.")
    assets = {}
    for name, (content_type, expected) in E7_FILES.items():
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("An E7 artifact is outside its package or is not a regular file.")
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError(f"E7 checksum mismatch for {name}: expected {expected}; got {actual}.")
        # Serve the verified bytes even if the package changes after startup.
        assets["/e7/" + name] = (data, content_type, None)
    return assets


def serve(assets):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.serve_asset()

        def do_HEAD(self):
            self.serve_asset()

        def do_OPTIONS(self):
            self.serve_asset()

        def log_message(self, *_args):
            pass

        def serve_asset(self):
            origin = self.headers.get("Origin")
            if self.headers.get("Host") != f"{HOST}:{PORT}" or (origin and origin not in ORIGINS):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path.startswith("/e7/"):
                if origin not in ORIGINS:
                    self.send_error(403)
                    return
                if self.path != path:
                    self.send_error(404)
                    return
            asset = assets.get(path)
            if not asset:
                self.send_error(404)
                return
            target, content_type, encoding = asset
            size = len(target) if isinstance(target, bytes) else target.stat().st_size
            byte_range = _parse_byte_range(self.headers.get("Range"), size)
            if self.command == "OPTIONS":
                self.send_response(204)
            elif byte_range is False:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
            else:
                start, end = byte_range or (0, size - 1)
                length = end - start + 1
                self.send_response(206 if byte_range else 200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                if byte_range:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                if encoding:
                    self.send_header("Content-Encoding", encoding)
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Range")
            self.send_header("Access-Control-Expose-Headers", "Accept-Ranges, Content-Range, Content-Length")
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command == "GET" and byte_range is not False:
                try:
                    with (BytesIO(target) if isinstance(target, bytes) else target.open("rb")) as file:
                        file.seek(start)
                        _write_stream_chunks(file, self.wfile, length)
                except ConnectionError:
                    pass

    class GeographyServer(ThreadingHTTPServer):
        request_queue_size = 32

    with GeographyServer((HOST, PORT), Handler) as server:
        print(f"Delhi geography ready on http://{HOST}:{PORT}/delhi/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    try:
        root = os.environ.get("DELHI_GEOGRAPHY_DIR")
        if not root or not Path(root).is_absolute():
            raise ValueError("Set DELHI_GEOGRAPHY_DIR to the absolute package directory.")
        assets = approved_assets(Path(root).resolve(strict=True))
        e7 = os.environ.get("DELHI_E7_DIR")
        if e7:
            assets.update(approved_e7_assets(e7))
        serve(assets)
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, KeyError) as error:
        sys.exit(str(error) if type(error) is ValueError else "Delhi geography startup failed.")
