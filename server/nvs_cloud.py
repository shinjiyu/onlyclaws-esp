"""Build an ESP-IDF NVS partition blob with OnlyClaws cloud (+ optional Wi-Fi) keys.

Uses a vendored copy of Espressif's nvs_partition_gen (Apache-2.0) for unencrypted
NVS v2 output. Arduino Preferences namespaces match firmware:

  cloud: host, prefix, device_id, token
  wifi:  ssid, pass
"""

from __future__ import annotations

import contextlib
import csv
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import vendor_nvs_partition_gen as nvs_gen

NVS_SIZE = 0x5000  # matches rlcd/partitions_*.csv
NVS_OFFSET = 0x9000


def build_cloud_nvs(
    *,
    host: str,
    prefix: str,
    device_id: str,
    token: str,
    wifi_ssid: Optional[str] = None,
    wifi_pass: Optional[str] = None,
    size: int = NVS_SIZE,
) -> bytes:
    """Return a raw NVS partition image (``size`` bytes) for flash at 0x9000."""
    host = (host or "").strip()
    prefix = (prefix or "/epaper").strip() or "/epaper"
    device_id = (device_id or "").strip().lower()
    token = (token or "").strip()
    if not host or not device_id or not token:
        raise ValueError("host, device_id, and token are required")
    if not device_id.isalnum():
        raise ValueError("device_id must be alphanumeric")

    rows: list[dict[str, str]] = [
        {"key": "cloud", "type": "namespace", "encoding": "", "value": ""},
        {"key": "host", "type": "data", "encoding": "string", "value": host},
        {"key": "prefix", "type": "data", "encoding": "string", "value": prefix},
        {"key": "device_id", "type": "data", "encoding": "string", "value": device_id},
        {"key": "token", "type": "data", "encoding": "string", "value": token},
    ]
    ssid = (wifi_ssid or "").strip()
    if ssid:
        rows.append({"key": "wifi", "type": "namespace", "encoding": "", "value": ""})
        rows.append({"key": "ssid", "type": "data", "encoding": "string", "value": ssid})
        rows.append(
            {
                "key": "pass",
                "type": "data",
                "encoding": "string",
                "value": wifi_pass or "",
            }
        )

    with tempfile.TemporaryDirectory(prefix="oc-nvs-") as td:
        tdir = Path(td)
        csv_path = tdir / "nvs.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["key", "type", "encoding", "value"])
            writer.writeheader()
            writer.writerows(rows)
        out_name = "nvs.bin"
        args = SimpleNamespace(
            input=str(csv_path),
            output=out_name,
            size=hex(size),
            outdir=str(tdir),
            version=2,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            nvs_gen.generate(args, is_encr_enabled=False)
        data = (tdir / out_name).read_bytes()
    if len(data) != size:
        raise RuntimeError(f"unexpected NVS size {len(data)} (want {size})")
    return data
