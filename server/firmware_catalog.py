"""Product firmware catalog for browser Web Serial flash (ESP Web Tools).

Public web-flash SKUs are marked web_flash=True (AMOLED 1.75C + Folo Passport).
Other PlatformIO envs stay packageable locally but are hidden unless `?all=1`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
FIRMWARE_DIR = Path(os.environ.get("OC_FIRMWARE_DIR", str(BASE_DIR / "firmware"))).resolve()

# ESP32 Arduino / PlatformIO default app layout (S3 CDC and classic ESP32).
DEFAULT_PARTS = (
    ("bootloader.bin", 0x0000),
    ("partitions.bin", 0x8000),
    ("boot_app0.bin", 0xE000),
    ("firmware.bin", 0x10000),
)

WEB_FLASH_DEFAULT_ID = "esp32-c3-folo-passport"

PRODUCTS: list[dict[str, Any]] = [
    {
        "id": "esp32-c3-folo-passport",
        "name": "OnlyClaws Folo AI Passport",
        "title_zh": "Folo AI Passport（C3+ST7789）",
        "chipFamily": "ESP32-C3",
        "serialType": "cdc",
        "pio_env": "esp32-c3-folo-passport",
        "product": "folo-passport",
        "blurb": "240×320 ST7789 + ES8311 — ESP32-C3, 8MB, no PSRAM",
        "web_flash": True,
        "planned": False,
    },
    {
        "id": "esp32-s3-amoled-175c",
        "name": "OnlyClaws AMOLED 1.75C",
        "title_zh": "圆形 AMOLED 1.75C 吧唧",
        "chipFamily": "ESP32-S3",
        "serialType": "cdc",
        "pio_env": "esp32-s3-amoled-175c",
        "product": "amoled-175c",
        "blurb": "466×466 round badge (panel stub until CO5300)",
        "web_flash": True,
        "planned": False,
    },
    # Local / ops packaging only (not listed on /flash by default).
    {
        "id": "esp32-s3-rlcd-42",
        "name": "OnlyClaws RLCD 4.2",
        "title_zh": "反射屏 RLCD 4.2\"",
        "chipFamily": "ESP32-S3",
        "serialType": "cdc",
        "pio_env": "esp32-s3-rlcd-42",
        "product": "rlcd-42",
        "blurb": "ST7305 400×300 + ES8311 + BLE",
        "web_flash": False,
        "planned": False,
    },
    {
        "id": "esp32-s3-epaper-397",
        "name": "OnlyClaws ePaper 3.97",
        "title_zh": "墨水屏 ePaper 3.97\"",
        "chipFamily": "ESP32-S3",
        "serialType": "cdc",
        "pio_env": "esp32-s3-epaper-397",
        "product": "epaper-397",
        "blurb": "800×480 partial refresh + ES8311",
        "web_flash": False,
        "planned": False,
    },
    {
        "id": "esp32-s3-bare",
        "name": "OnlyClaws ESP32-S3 bare",
        "title_zh": "裸 ESP32-S3（无屏）",
        "chipFamily": "ESP32-S3",
        "serialType": "cdc",
        "pio_env": "esp32-s3-bare",
        "product": "s3-bare",
        "blurb": "Cloud + Lua only",
        "web_flash": False,
        "planned": False,
    },
    {
        "id": "esp32-roarm-m2",
        "name": "OnlyClaws RoArm-M2",
        "title_zh": "RoArm-M2 机械臂驱动板",
        "chipFamily": "ESP32",
        "serialType": "uart",
        "pio_env": "esp32-roarm-m2",
        "product": "roarm-m2",
        "blurb": "STS bus, no panel",
        "web_flash": False,
        "planned": False,
    },
]


def product_dir(product_id: str) -> Path:
    return FIRMWARE_DIR / product_id


def _version_file(pdir: Path) -> str:
    vf = pdir / "VERSION"
    if vf.is_file():
        return vf.read_text(encoding="utf-8").strip() or "dev"
    return "dev"


def parts_ready(pdir: Path) -> bool:
    if (pdir / "merged.bin").is_file():
        return True
    return all((pdir / name).is_file() for name, _ in DEFAULT_PARTS)


def build_manifest(product: dict[str, Any], *, public_base: str = "") -> dict[str, Any]:
    """ESP Web Tools manifest. Paths are absolute from site root when public_base set."""
    pid = product["id"]
    pdir = product_dir(pid)
    version = _version_file(pdir)
    base = f"{public_base.rstrip('/')}/firmware/{pid}" if public_base else f"/firmware/{pid}"

    build: dict[str, Any] = {"chipFamily": product["chipFamily"]}
    if product.get("serialType"):
        build["serialType"] = product["serialType"]

    if (pdir / "merged.bin").is_file():
        build["parts"] = [{"path": f"{base}/merged.bin", "offset": 0}]
    else:
        build["parts"] = [
            {"path": f"{base}/{name}", "offset": off} for name, off in DEFAULT_PARTS
        ]

    return {
        "name": product["name"],
        "version": version,
        "new_install_prompt_erase": True,
        "builds": [build],
    }


def list_products(*, include_all: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in PRODUCTS:
        if not include_all and not p.get("web_flash"):
            continue
        pdir = product_dir(p["id"])
        ready = parts_ready(pdir)
        out.append(
            {
                "id": p["id"],
                "name": p["name"],
                "title_zh": p.get("title_zh") or p["name"],
                "chipFamily": p["chipFamily"],
                "serialType": p.get("serialType"),
                "product": p.get("product"),
                "blurb": p.get("blurb") or "",
                "planned": bool(p.get("planned")),
                "web_flash": bool(p.get("web_flash")),
                "ready": ready,
                "version": _version_file(pdir) if ready else None,
                "manifest_url": f"/api/firmware/{p['id']}/manifest.json",
                "pio_env": p.get("pio_env"),
            }
        )
    return out


def get_product(product_id: str) -> dict[str, Any] | None:
    for p in PRODUCTS:
        if p["id"] == product_id:
            return p
    return None


def write_static_manifest(product_id: str) -> Path:
    """Write server/firmware/<id>/manifest.json for static hosting / packaging."""
    product = get_product(product_id)
    if not product:
        raise KeyError(product_id)
    pdir = product_dir(product_id)
    pdir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(product)
    path = pdir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path
