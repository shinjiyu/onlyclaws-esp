"""Unit tests for web-flash firmware catalog (no FastAPI required)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import firmware_catalog as fc


def test_public_list_is_amoled_only():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        products = fc.list_products()
        assert [p["id"] for p in products] == ["esp32-s3-amoled-175c"]
        assert products[0]["web_flash"] is True


def test_all_includes_ops_skus():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        ids = {p["id"] for p in fc.list_products(include_all=True)}
        assert "esp32-s3-amoled-175c" in ids
        assert "esp32-s3-rlcd-42" in ids
        assert "esp32-roarm-m2" in ids


def test_ready_when_parts_present():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        pdir = Path(td) / "esp32-s3-amoled-175c"
        pdir.mkdir()
        for name, _ in fc.DEFAULT_PARTS:
            (pdir / name).write_bytes(b"x")
        (pdir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        products = {p["id"]: p for p in fc.list_products()}
        assert products["esp32-s3-amoled-175c"]["ready"] is True
        assert products["esp32-s3-amoled-175c"]["version"] == "1.2.3"


def test_manifest_absolute_paths():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        pdir = Path(td) / "esp32-s3-amoled-175c"
        pdir.mkdir()
        for name, _ in fc.DEFAULT_PARTS:
            (pdir / name).write_bytes(b"x")
        product = fc.get_product("esp32-s3-amoled-175c")
        assert product is not None
        man = fc.build_manifest(product)
        assert man["builds"][0]["chipFamily"] == "ESP32-S3"
        assert man["builds"][0]["serialType"] == "cdc"
        paths = [part["path"] for part in man["builds"][0]["parts"]]
        assert paths[0].startswith("/firmware/esp32-s3-amoled-175c/")
        assert paths[-1].endswith("firmware.bin")
        assert man["builds"][0]["parts"][-1]["offset"] == 0x10000


def test_write_static_manifest():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        path = fc.write_static_manifest("esp32-s3-amoled-175c")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["name"].startswith("OnlyClaws")
        assert path.parent.name == "esp32-s3-amoled-175c"


if __name__ == "__main__":
    test_public_list_is_amoled_only()
    test_all_includes_ops_skus()
    test_ready_when_parts_present()
    test_manifest_absolute_paths()
    test_write_static_manifest()
    print("ok")
