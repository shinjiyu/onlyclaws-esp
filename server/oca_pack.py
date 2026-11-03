"""OCA install package: stock unsigned APK + one phone's assets/session.json, re-signed.

The base APK comes from android/scripts/package_oca_base.sh. Signing uses one fixed
keystore so a new package installs over an earlier one. See ADR 0009.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

OCA_DIR = Path(os.environ.get("OC_OCA_DIR", Path(__file__).resolve().parent / "oca"))
BASE_APK = "oca-base.apk"
SESSION_ASSET = "assets/session.json"
APK_NAME = "onlyclaws-oca.apk"

_SIGNATURE_SUFFIXES = (".SF", ".RSA", ".DSA", ".EC")


def session_json(device_id: str, token: str) -> bytes:
    body = {"device_id": device_id, "token": token}
    return (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def base_apk() -> Path:
    return OCA_DIR / BASE_APK


def version() -> Optional[str]:
    path = OCA_DIR / "VERSION"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _build_tool(name: str, env_key: str) -> Optional[str]:
    explicit = os.environ.get(env_key, "").strip()
    if explicit:
        return explicit if Path(explicit).is_file() else None
    found = shutil.which(name)
    if found:
        return found
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        sdk = os.environ.get(key, "").strip()
        if not sdk:
            continue
        tools = sorted((Path(sdk) / "build-tools").glob(f"*/{name}"))
        if tools:
            return str(tools[-1])
    return None


def apksigner() -> Optional[str]:
    return _build_tool("apksigner", "OC_OCA_APKSIGNER")


def zipalign() -> Optional[str]:
    return _build_tool("zipalign", "OC_OCA_ZIPALIGN")


def keystore() -> Optional[Path]:
    raw = os.environ.get("OC_OCA_KEYSTORE", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def status() -> dict:
    missing: list[str] = []
    if not base_apk().is_file():
        missing.append("base_apk")
    if keystore() is None or not os.environ.get("OC_OCA_KEYSTORE_PASS"):
        missing.append("keystore")
    if apksigner() is None:
        missing.append("apksigner")
    if zipalign() is None:
        missing.append("zipalign")
    return {
        "ready": not missing,
        "version": version(),
        "missing": missing,
        "session_asset": SESSION_ASSET,
    }


def _is_signature_entry(name: str) -> bool:
    if not name.startswith("META-INF/"):
        return False
    base = name[len("META-INF/") :]
    if "/" in base:
        return False
    return base == "MANIFEST.MF" or base.upper().endswith(_SIGNATURE_SUFFIXES)


def inject_session(src: Path, dst: Path, payload: bytes) -> None:
    """Copy src to dst with SESSION_ASSET replaced; entries keep their compression."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            if info.filename == SESSION_ASSET or _is_signature_entry(info.filename):
                continue
            out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            out.compress_type = info.compress_type
            out.external_attr = info.external_attr
            out.extra = b""
            zout.writestr(out, zin.read(info.filename))
        asset = zipfile.ZipInfo(SESSION_ASSET, date_time=(2020, 1, 1, 0, 0, 0))
        asset.compress_type = zipfile.ZIP_DEFLATED
        asset.external_attr = 0o644 << 16
        zout.writestr(asset, payload)


class PackError(RuntimeError):
    pass


def _run(cmd: list[str], env: dict[str, str]) -> None:
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise PackError(f"{Path(cmd[0]).name} failed: {' / '.join(tail)}")


def build_apk(device_id: str, token: str) -> bytes:
    st = status()
    if not st["ready"]:
        raise PackError("OCA package not configured: " + ", ".join(st["missing"]))
    ks = keystore()
    assert ks is not None
    env = dict(os.environ)
    env["OC_OCA_KS_PASS"] = os.environ["OC_OCA_KEYSTORE_PASS"]
    env["OC_OCA_K_PASS"] = os.environ.get("OC_OCA_KEY_PASS") or env["OC_OCA_KS_PASS"]
    with tempfile.TemporaryDirectory(prefix="oca-pack-") as td:
        work = Path(td)
        injected = work / "injected.apk"
        aligned = work / "aligned.apk"
        signed = work / APK_NAME
        inject_session(base_apk(), injected, session_json(device_id, token))
        _run([str(zipalign()), "-p", "-f", "4", str(injected), str(aligned)], env)
        cmd = [
            str(apksigner()),
            "sign",
            "--ks",
            str(ks),
            "--ks-pass",
            "env:OC_OCA_KS_PASS",
            "--key-pass",
            "env:OC_OCA_K_PASS",
            "--out",
            str(signed),
        ]
        alias = os.environ.get("OC_OCA_KEY_ALIAS", "").strip()
        if alias:
            cmd[2:2] = ["--ks-key-alias", alias]
        cmd.append(str(aligned))
        _run(cmd, env)
        return signed.read_bytes()
