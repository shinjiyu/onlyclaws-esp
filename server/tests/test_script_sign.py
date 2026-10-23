"""Control-plane Ed25519 script envelopes."""

from __future__ import annotations

import base64
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

import script_sign  # noqa: E402


def _key(tmp: Path) -> Path:
    key = tmp / "key.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    return key


def test_prefix_layout_and_openssl_roundtrip(tmp_path: Path):
    key = _key(tmp_path)
    source = "print(1)\n"
    prefix = script_sign.build_prefix("abcd", source, "once", 250, 3)
    assert prefix[:4] == b"LCLW"
    assert prefix[4] == 1
    assert prefix[5:9] == b"abcd"
    assert prefix[9:37] == b"\x00" * 28
    assert prefix[37] == 1 and prefix[38] == 0
    assert int.from_bytes(prefix[39:43], "little") == 250
    assert int.from_bytes(prefix[43:47], "little") == len(source)
    assert int.from_bytes(prefix[47:51], "little") == 3
    assert prefix[51:83] == hashlib.sha256(source.encode()).digest()
    assert prefix[83:] == source.encode()

    fields = script_sign.signed_script_fields(
        script_id="abcd",
        source=source,
        mode="once",
        every_ms=250,
        version=3,
        key_path=key,
    )
    assert fields["sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert fields["version"] == 3
    sig = base64.b64decode(fields["sig"])
    assert len(sig) == 64
    (tmp_path / "sig").write_bytes(sig)
    (tmp_path / "prefix").write_bytes(prefix)
    pub = tmp_path / "pub.pem"
    subprocess.run(
        ["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(pub)],
        check=True,
        capture_output=True,
    )
    ok = subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(pub),
            "-rawin",
            "-sigfile",
            str(tmp_path / "sig"),
            "-in",
            str(tmp_path / "prefix"),
        ],
        capture_output=True,
    )
    assert ok.returncode == 0

    raw = script_sign.raw_public_key(key)
    assert len(raw) == 32
    header = (ROOT / "rlcd" / "include" / "cloud_config.h").read_text()
    assert 'OC_SCRIPT_PUBKEY_HEX "' in header
    hexkey = header.split('OC_SCRIPT_PUBKEY_HEX "')[1].split('"')[0]
    # Empty until an operator pastes a key. Firmware then refuses every script.
    assert hexkey == "" or (
        len(hexkey) == 64 and all(c in "0123456789abcdefABCDEF" for c in hexkey)
    )


def test_next_version_and_rejections(tmp_path: Path):
    assert script_sign.next_version(None) == 1
    assert script_sign.next_version(0) == 1
    assert script_sign.next_version("4") == 5
    with pytest.raises(script_sign.ScriptSignError):
        script_sign.next_version(0xFFFFFFFF)
    with pytest.raises(script_sign.ScriptSignError):
        script_sign.build_prefix("../x", "a", "loop", 1000, 1)
    with pytest.raises(script_sign.ScriptSignError):
        script_sign.build_prefix("ab", "", "loop", 1000, 1)
    with pytest.raises(script_sign.ScriptSignError):
        script_sign.build_prefix("ab", "a", "nope", 1000, 1)
    with pytest.raises(FileNotFoundError):
        script_sign.sign_prefix(b"x" * 84, tmp_path / "missing.pem")


def test_deploy_path_signs(tmp_path: Path):
    src = (ROOT / "server" / "app.py").read_text()
    assert "signed_script_fields" in src
    assert "script_version" in src
    assert "EPD_SCRIPT_SIGNING_KEY" in src
    key = _key(tmp_path)
    fields = script_sign.signed_script_fields(
        script_id="f" * 32,
        source="x=1\n",
        mode="loop",
        every_ms=1000,
        version=script_sign.next_version(2),
        key_path=key,
    )
    assert fields["version"] == 3
    blob = script_sign.signed_blob(
        script_id="f" * 32,
        source="x=1\n",
        mode="loop",
        every_ms=1000,
        version=3,
        key_path=key,
    )
    assert blob.endswith(base64.b64decode(fields["sig"]))
