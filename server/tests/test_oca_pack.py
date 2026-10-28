"""OCA install package: session injection, signing pipeline, owner-only routes (ADR 0009)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import oca_pack  # noqa: E402

SIG_FILES = ("META-INF/MANIFEST.MF", "META-INF/CERT.SF", "META-INF/CERT.RSA")


def _fake_apk(path: Path, with_session: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("AndroidManifest.xml"), b"<manifest/>", zipfile.ZIP_DEFLATED)
        z.writestr("resources.arsc", b"\0" * 64, zipfile.ZIP_STORED)
        z.writestr("lib/arm64-v8a/libx.so", b"\x7fELF" + b"\0" * 32, zipfile.ZIP_STORED)
        z.writestr("assets/boot.js", b"function onStart() {}\n", zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/services/x", b"keep", zipfile.ZIP_DEFLATED)
        for name in SIG_FILES:
            z.writestr(name, b"old", zipfile.ZIP_DEFLATED)
        if with_session:
            z.writestr(oca_pack.SESSION_ASSET, b'{"device_id":"old"}', zipfile.ZIP_DEFLATED)


def _script(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def oca_dir(tmp_path, monkeypatch):
    for key in (
        "OC_OCA_KEYSTORE",
        "OC_OCA_KEYSTORE_PASS",
        "OC_OCA_KEY_ALIAS",
        "OC_OCA_KEY_PASS",
        "OC_OCA_APKSIGNER",
        "OC_OCA_ZIPALIGN",
        "ANDROID_HOME",
        "ANDROID_SDK_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(oca_pack, "OCA_DIR", tmp_path)
    return tmp_path


def test_session_json_shape():
    data = json.loads(oca_pack.session_json("oca0123abcd", "tok"))
    assert data == {"device_id": "oca0123abcd", "token": "tok"}


def test_inject_replaces_session_keeps_storage_drops_signature(tmp_path):
    src, dst = tmp_path / "in.apk", tmp_path / "out.apk"
    _fake_apk(src, with_session=True)
    payload = oca_pack.session_json("oca1", "t1")
    oca_pack.inject_session(src, dst, payload)
    with zipfile.ZipFile(dst) as z:
        names = z.namelist()
        assert names.count(oca_pack.SESSION_ASSET) == 1
        assert z.read(oca_pack.SESSION_ASSET) == payload
        for name in SIG_FILES:
            assert name not in names
        assert z.read("META-INF/services/x") == b"keep"
        assert z.getinfo("resources.arsc").compress_type == zipfile.ZIP_STORED
        assert z.getinfo("lib/arm64-v8a/libx.so").compress_type == zipfile.ZIP_STORED
        assert z.getinfo("assets/boot.js").compress_type == zipfile.ZIP_DEFLATED


def test_status_lists_missing_pieces(oca_dir):
    st = oca_pack.status()
    assert st["ready"] is False
    assert set(st["missing"]) == {"base_apk", "keystore", "apksigner", "zipalign"}
    with pytest.raises(oca_pack.PackError):
        oca_pack.build_apk("oca1", "t")


def test_build_runs_zipalign_then_apksigner(oca_dir, tmp_path, monkeypatch):
    _fake_apk(oca_dir / oca_pack.BASE_APK)
    (oca_dir / "VERSION").write_text("0.7.0\n", encoding="utf-8")
    ks = tmp_path / "oca.jks"
    ks.write_bytes(b"ks")
    log = tmp_path / "calls.txt"
    zipalign = _script(
        tmp_path / "zipalign",
        "import shutil, sys\n"
        f"open({str(log)!r}, 'a').write('zipalign ' + ' '.join(sys.argv[1:4]) + '\\n')\n"
        "shutil.copy(sys.argv[-2], sys.argv[-1])\n",
    )
    apksigner = _script(
        tmp_path / "apksigner",
        "import os, shutil, sys\n"
        "a = sys.argv[1:]\n"
        "assert a[0] == 'sign'\n"
        "assert os.environ[a[a.index('--ks-pass') + 1][4:]] == 'secret'\n"
        "assert os.environ[a[a.index('--key-pass') + 1][4:]] == 'secret'\n"
        f"open({str(log)!r}, 'a').write('apksigner ' + a[a.index('--ks-key-alias') + 1] + '\\n')\n"
        "shutil.copy(a[-1], a[a.index('--out') + 1])\n",
    )
    monkeypatch.setenv("OC_OCA_ZIPALIGN", str(zipalign))
    monkeypatch.setenv("OC_OCA_APKSIGNER", str(apksigner))
    monkeypatch.setenv("OC_OCA_KEYSTORE", str(ks))
    monkeypatch.setenv("OC_OCA_KEYSTORE_PASS", "secret")
    monkeypatch.setenv("OC_OCA_KEY_ALIAS", "oca")
    st = oca_pack.status()
    assert st["ready"] is True and st["version"] == "0.7.0"

    apk = oca_pack.build_apk("oca1", "t1")
    out = tmp_path / "got.apk"
    out.write_bytes(apk)
    with zipfile.ZipFile(out) as z:
        assert json.loads(z.read(oca_pack.SESSION_ASSET))["token"] == "t1"
    assert log.read_text(encoding="utf-8").splitlines() == ["zipalign -p -f 4", "apksigner oca"]


def test_sign_failure_is_pack_error(oca_dir, tmp_path, monkeypatch):
    _fake_apk(oca_dir / oca_pack.BASE_APK)
    ks = tmp_path / "oca.jks"
    ks.write_bytes(b"ks")
    ok = _script(tmp_path / "zipalign", "import shutil, sys\nshutil.copy(sys.argv[-2], sys.argv[-1])\n")
    bad = _script(tmp_path / "apksigner", "import sys\nsys.stderr.write('bad password\\n')\nsys.exit(1)\n")
    monkeypatch.setenv("OC_OCA_ZIPALIGN", str(ok))
    monkeypatch.setenv("OC_OCA_APKSIGNER", str(bad))
    monkeypatch.setenv("OC_OCA_KEYSTORE", str(ks))
    monkeypatch.setenv("OC_OCA_KEYSTORE_PASS", "x")
    with pytest.raises(oca_pack.PackError, match="bad password"):
        oca_pack.build_apk("oca1", "t")


@pytest.mark.skipif(
    not os.environ.get("OC_OCA_E2E"),
    reason="set OC_OCA_E2E=1 with a real base APK, keystore and build-tools",
)
def test_real_apk_verifies():
    st = oca_pack.status()
    assert st["ready"], st
    apk = oca_pack.build_apk("oca0e2etest", "tok-e2e")
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "oca-e2e.apk"
    tmp.write_bytes(apk)
    proc = subprocess.run(
        [oca_pack.apksigner(), "verify", "--min-sdk-version", "26", str(tmp)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    with zipfile.ZipFile(tmp) as z:
        assert json.loads(z.read(oca_pack.SESSION_ASSET))["device_id"] == "oca0e2etest"
    if shutil.which("zipalign") or oca_pack.zipalign():
        check = subprocess.run([oca_pack.zipalign(), "-c", "-p", "4", str(tmp)], capture_output=True)
        assert check.returncode == 0


# ---- routes ----


def _agent_token(oc_app, email: str) -> str:
    with oc_app.db() as conn:
        return oc_app.tenancy.create_agent_control_token(conn, email=email)["token"]


def test_create_requires_browser_login(oc_app, client, login):
    assert client.post("/api/oca/devices", json={}).status_code == 401
    token = _agent_token(oc_app, "agent-owner@example.com")
    r = client.post(
        "/api/oca/devices", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


def test_create_lists_as_oca(oc_app, client, login):
    login(client, "phone-owner@example.com")
    r = client.post("/api/oca/devices", json={"name": "Pixel"})
    assert r.status_code == 200, r.text
    dev = r.json()["device"]
    assert dev["id"].startswith("oca") and len(dev["id"]) == 12 and dev["id"].isalnum()
    assert dev["kind"] == "oca"
    listed = {d["id"]: d for d in client.get("/api/devices").json()["devices"]}
    assert listed[dev["id"]]["kind"] == "oca"
    assert listed[dev["id"]]["name"] == "Pixel"
    assert listed[dev["id"]]["has_token"] is False
    assert listed[dev["id"]]["width"] is None


def test_session_download_rotates_token(oc_app, client, login):
    login(client, "rotate@example.com")
    did = client.post("/api/oca/devices", json={}).json()["device"]["id"]
    first = client.post(f"/api/oca/devices/{did}/session")
    assert first.status_code == 200
    assert "attachment" in first.headers["content-disposition"]
    tok1 = first.json()["token"]
    assert first.json()["device_id"] == did
    tok2 = client.post(f"/api/oca/devices/{did}/session").json()["token"]
    assert tok1 != tok2
    with oc_app.db() as conn:
        oc_app.tenancy.verify_device_token(conn, did, tok2)
        with pytest.raises(Exception):
            oc_app.tenancy.verify_device_token(conn, did, tok1)


def test_apk_503_when_unconfigured_and_token_kept(oc_app, client, login, monkeypatch, tmp_path):
    monkeypatch.setattr(oca_pack, "OCA_DIR", tmp_path)
    login(client, "apk503@example.com")
    did = client.post("/api/oca/devices", json={}).json()["device"]["id"]
    tok = client.post(f"/api/oca/devices/{did}/session").json()["token"]
    r = client.post(f"/api/oca/devices/{did}/apk")
    assert r.status_code == 503
    with oc_app.db() as conn:
        oc_app.tenancy.verify_device_token(conn, did, tok)
    st = client.get("/api/oca/package").json()
    assert st["ready"] is False and "base_apk" in st["missing"]


def test_apk_returns_signed_package(oc_app, client, login, monkeypatch, tmp_path):
    monkeypatch.setattr(oca_pack, "status", lambda: {"ready": True, "missing": [], "version": "t"})
    monkeypatch.setattr(oca_pack, "build_apk", lambda did, tok: oca_pack.session_json(did, tok))
    login(client, "apkok@example.com")
    did = client.post("/api/oca/devices", json={}).json()["device"]["id"]
    r = client.post(f"/api/oca/devices/{did}/apk")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
    assert f"onlyclaws-oca-{did}.apk" in r.headers["content-disposition"]
    with oc_app.db() as conn:
        oc_app.tenancy.verify_device_token(conn, did, json.loads(r.content)["token"])


def test_other_owner_and_board_rejected(oc_app, client, login):
    login(client, "alice@example.com")
    did = client.post("/api/oca/devices", json={}).json()["device"]["id"]
    board = client.post("/api/devices/register", json={"device_id": "a1b2c3d4e5f6"})
    assert board.status_code == 200
    assert client.post("/api/oca/devices/a1b2c3d4e5f6/session").status_code == 400
    login(client, "bob@example.com")
    assert client.post(f"/api/oca/devices/{did}/session").status_code in (403, 404)
    assert client.post(f"/api/oca/devices/{did}/apk").status_code in (403, 404)
