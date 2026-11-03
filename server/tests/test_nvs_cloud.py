"""NVS blob used by login-gated web flash."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nvs_cloud


def test_build_cloud_nvs_size_and_strings():
    blob = nvs_cloud.build_cloud_nvs(
        host="onlyclaws.world",
        prefix="/epaper",
        device_id="aabbccddeeff",
        token="tok_deadbeef",
    )
    assert len(blob) == nvs_cloud.NVS_SIZE
    assert b"cloud" in blob
    assert b"onlyclaws.world" in blob
    assert b"/epaper" in blob
    assert b"aabbccddeeff" in blob
    assert b"tok_deadbeef" in blob


def test_build_cloud_nvs_with_wifi():
    blob = nvs_cloud.build_cloud_nvs(
        host="onlyclaws.world",
        prefix="/epaper",
        device_id="aabbccddeeff",
        token="tok_deadbeef",
        wifi_ssid="HomeNet",
        wifi_pass="secret",
    )
    assert b"wifi" in blob
    assert b"HomeNet" in blob
    assert b"secret" in blob


def test_rejects_bad_device_id():
    try:
        nvs_cloud.build_cloud_nvs(
            host="onlyclaws.world",
            prefix="/epaper",
            device_id="aa:bb",
            token="tok",
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


if __name__ == "__main__":
    test_build_cloud_nvs_size_and_strings()
    test_build_cloud_nvs_with_wifi()
    test_rejects_bad_device_id()
    print("ok")
