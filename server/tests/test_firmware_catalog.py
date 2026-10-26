"""Unit tests for web-flash firmware catalog (no FastAPI required)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import firmware_catalog as fc


def test_public_list_has_passport_and_amoled():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        products = fc.list_products()
        ids = [p["id"] for p in products]
        assert ids == ["esp32-c3-folo-passport", "esp32-s3-amoled-175c"]
        assert all(p["web_flash"] for p in products)


def test_all_includes_ops_skus():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        ids = {p["id"] for p in fc.list_products(include_all=True)}
        assert "esp32-c3-folo-passport" in ids
        assert "esp32-s3-rlcd-42" in ids
        assert "esp32-roarm-m2" in ids


def test_ready_when_parts_present():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        pdir = Path(td) / "esp32-c3-folo-passport"
        pdir.mkdir()
        for name, _ in fc.DEFAULT_PARTS:
            (pdir / name).write_bytes(b"x")
        (pdir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        products = {p["id"]: p for p in fc.list_products()}
        assert products["esp32-c3-folo-passport"]["ready"] is True
        assert products["esp32-c3-folo-passport"]["version"] == "1.2.3"
        assert products["esp32-c3-folo-passport"]["chipFamily"] == "ESP32-C3"


def test_manifest_c3():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        pdir = Path(td) / "esp32-c3-folo-passport"
        pdir.mkdir()
        for name, _ in fc.DEFAULT_PARTS:
            (pdir / name).write_bytes(b"x")
        product = fc.get_product("esp32-c3-folo-passport")
        man = fc.build_manifest(product)
        assert man["builds"][0]["chipFamily"] == "ESP32-C3"
        assert man["builds"][0]["serialType"] == "cdc"


def test_write_static_manifest():
    with tempfile.TemporaryDirectory() as td:
        fc.FIRMWARE_DIR = Path(td)
        path = fc.write_static_manifest("esp32-c3-folo-passport")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "Passport" in data["name"]


if __name__ == "__main__":
    test_public_list_has_passport_and_amoled()
    test_all_includes_ops_skus()
    test_ready_when_parts_present()
    test_manifest_c3()
    test_write_static_manifest()
    print("ok")
