"""Unit tests for pipeline path security and destination helpers."""

import tempfile
import unittest
from pathlib import Path

from pipeline.paths import load_c6_config, output_destination, pack_destination


class PathsTests(unittest.TestCase):
    def test_pack_destination_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dest = pack_destination(root, None, "test.parquet")
            self.assertEqual(dest, root / "test.parquet")

            dest2 = pack_destination(root, Path("subdir/test.parquet"), "fallback.parquet")
            self.assertEqual(dest2, (root / "subdir/test.parquet").resolve())

    def test_pack_destination_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root.parent / "escape.txt"
            with self.assertRaises(ValueError):
                pack_destination(root, outside, "default.txt")

    def test_output_destination_valid(self):
        project_root = Path(__file__).resolve().parents[2]
        dest = output_destination(Path("out/delhi/test.json"))
        self.assertEqual(dest, (project_root / "out/delhi/test.json").resolve())

    def test_output_destination_rejects_escape(self):
        with self.assertRaises(ValueError):
            output_destination(Path("data/raw/escape.txt"))

    def test_load_c6_config_valid(self):
        project_root = Path(__file__).resolve().parents[2]
        cfg_path, cfg = load_c6_config(project_root / "configs" / "delhi.yaml")
        self.assertEqual(cfg.get("contract"), "C6@1.0")
        self.assertEqual(cfg.get("city"), "delhi")

    def test_load_c6_config_rejects_outside_configs(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml") as f:
            with self.assertRaises(ValueError):
                load_c6_config(Path(f.name))


if __name__ == "__main__":
    unittest.main()
