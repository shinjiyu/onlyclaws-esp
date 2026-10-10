"""Model registry: op set parity with firmware, TFLite parsing, manifest rules, signing, routes."""

from __future__ import annotations

import base64
import json
import random
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

import ml_opset  # noqa: E402
import ml_registry  # noqa: E402

MODELS = ROOT / "ml" / "models" / "micro_speech"
ENGINE = ROOT / "rlcd" / "src" / "ml_engine.cpp"
MANIFEST_H = ROOT / "rlcd" / "include" / "ml_manifest.h"


def _blob(name: str) -> bytes:
    return (MODELS / f"{name}.tflite").read_bytes()


def _meta(name: str) -> dict:
    return json.loads((MODELS / f"{name}.meta.json").read_text())


# ---- firmware parity ----


def test_opset_matches_firmware_resolver():
    src = ENGINE.read_text()
    body = src[src.index("bool registerOpsetV1(") :]
    body = body[: body.index("\n}\n")]
    firmware = re.findall(r"ok &= r\.Add(\w+)\(\) == kTfLiteOk;", body)
    assert len(firmware) == len(set(firmware))
    server = set(ml_opset.BUILTINS_V1) | set(ml_opset.CUSTOMS_V1)
    assert set(firmware) == server
    resolver = re.search(r"kMaxOps = (\d+);", src)
    assert resolver and int(resolver.group(1)) >= len(firmware)


def test_limits_match_firmware():
    h = MANIFEST_H.read_text()
    assert f"kMlOpsetVersion = {ml_opset.OPSET_VERSION};" in h
    assert f"kMlMaxArenaKb = {ml_registry.MAX_ARENA_KB};" in h
    assert "kMlMaxModelBytes = 2u * 1024u * 1024u;" in h
    assert ml_registry.MAX_MODEL_BYTES == 2 * 1024 * 1024


# ---- TFLite parsing ----


def test_real_models_pass_opset():
    for name in ("micro_speech", "ms_frontend"):
        ml_registry.check_opset(_blob(name))
    builtins, customs, version = ml_registry.tflite_op_codes(_blob("ms_frontend"))
    assert version == 3
    assert "SignalRfft" in customs and ml_opset.BUILTINS_V1["Cast"] in builtins


def test_op_outside_set_rejected(monkeypatch):
    b, c = ml_opset.OPSETS[1]
    monkeypatch.setitem(
        ml_opset.OPSETS, 1, (b - {ml_opset.BUILTINS_V1["Softmax"]}, c - {"SignalPCAN"})
    )
    with pytest.raises(ml_registry.TfliteError, match="Softmax"):
        ml_registry.check_opset(_blob("micro_speech"))
    with pytest.raises(ml_registry.TfliteError, match="SignalPCAN"):
        ml_registry.check_opset(_blob("ms_frontend"))


def test_not_tflite_rejected():
    with pytest.raises(ml_registry.TfliteError):
        ml_registry.check_opset(b"\x00" * 64)


def test_malformed_input_only_raises_tflite_error():
    rng = random.Random(7)
    good = _blob("ms_frontend")
    cases = [good[:n] for n in range(0, len(good), 97)]
    for _ in range(300):
        b = bytearray(good)
        for _ in range(rng.randint(1, 8)):
            b[rng.randrange(8, len(b))] = rng.randrange(256)
        cases.append(bytes(b))
    for case in cases:
        try:
            ml_registry.tflite_op_codes(case)
        except ml_registry.TfliteError:
            pass


# ---- manifest ----


def test_manifest_audio_ok():
    m = ml_registry.build_manifest(_meta("micro_speech"), _blob("micro_speech"), 3)
    assert m["version"] == 3 and m["opset"] == 1 and m["bytes"] == 18800
    assert m["audio"]["frontend"] == "ms_frontend" and len(m["sha256"]) == 64
    raw = ml_registry.manifest_bytes(m)
    assert json.loads(raw) == m and len(raw) < 4096


@pytest.mark.parametrize(
    "patch,needle",
    [
        ({"name": "Bad Name"}, "name"),
        ({"kind": "video"}, "kind"),
        ({"arena_kb": 0}, "arena_kb"),
        ({"arena_kb": 2048}, "arena_kb"),
        ({"labels": ["x" * 33]}, "labels"),
        ({"audio": None}, "audio"),
    ],
)
def test_manifest_rejects(patch, needle):
    meta = {**_meta("micro_speech"), **patch}
    with pytest.raises(HTTPException) as e:
        ml_registry.build_manifest(meta, b"x", 1)
    assert needle in e.value.detail


@pytest.mark.parametrize(
    "audio,needle",
    [
        ({"rate": 44100}, "16000"),
        ({"frames": 600}, "frames"),
        ({"frames": 500, "stride_ms": 1000}, "10 s"),
        ({"frontend": "micro_speech"}, "frontend"),
    ],
)
def test_manifest_audio_rejects(audio, needle):
    meta = _meta("micro_speech")
    meta["audio"] = {**meta["audio"], **audio}
    with pytest.raises(HTTPException) as e:
        ml_registry.build_manifest(meta, b"x", 1)
    assert needle in e.value.detail


# ---- signing + routes ----


@pytest.fixture()
def keypair(tmp_path):
    key = tmp_path / "k.pem"
    pub = tmp_path / "k.pub"
    subprocess.run(
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "ec", "-in", str(key), "-pubout", "-out", str(pub)],
        check=True,
        capture_output=True,
    )
    return key, pub


def _verify(pub: Path, data: bytes, sig_b64: str, tmp_path: Path) -> bool:
    sig = tmp_path / "sig.der"
    sig.write_bytes(base64.b64decode(sig_b64))
    r = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sig)],
        input=data,
        capture_output=True,
    )
    return r.returncode == 0


@pytest.fixture()
def client(tmp_path, keypair, monkeypatch):
    key, _ = keypair
    monkeypatch.setenv("EPD_ML_SIGNING_KEY", str(key))
    dbfile = tmp_path / "t.db"
    conn = sqlite3.connect(dbfile)
    conn.execute("CREATE TABLE devices (id TEXT PRIMARY KEY, owner_email TEXT)")
    conn.execute("INSERT INTO devices VALUES ('dev1', 'alice@x.io'), ('dev2', 'bob@x.io')")
    conn.commit()
    conn.close()

    def db():
        c = sqlite3.connect(dbfile)
        c.row_factory = sqlite3.Row
        return c

    def require_user(request: Request):
        email = request.headers.get("X-Test-User")
        if not email:
            raise HTTPException(status_code=401)
        return {"email": email}

    def require_device(device_id: str, request: Request):
        if request.headers.get("Authorization") != f"Bearer tok-{device_id}":
            raise HTTPException(status_code=401)
        return device_id

    app = FastAPI()
    app.include_router(
        ml_registry.make_router(
            require_user=require_user, require_device=require_device, db=db, data_dir=tmp_path
        )
    )
    return TestClient(app)


def _upload(client, name, user="alice@x.io", meta=None, blob=None):
    return client.post(
        "/api/ml/models",
        headers={"X-Test-User": user},
        files={"file": ("m.tflite", blob if blob is not None else _blob(name))},
        data={"meta": json.dumps(meta or _meta(name))},
    )


def test_end_to_end(client, keypair, tmp_path):
    _, pub = keypair
    r = _upload(client, "micro_speech")
    assert r.status_code == 400 and "frontend" in r.json()["detail"]
    assert _upload(client, "ms_frontend").status_code == 200
    r = _upload(client, "micro_speech")
    assert r.status_code == 200 and r.json()["version"] == 1
    assert _upload(client, "micro_speech").json()["version"] == 2

    listed = client.get("/api/ml/models", headers={"X-Test-User": "alice@x.io"}).json()
    assert [m["name"] for m in listed["models"]] == ["micro_speech", "ms_frontend"]
    assert client.get("/api/ml/models", headers={"X-Test-User": "bob@x.io"}).json() == {
        "models": []
    }

    auth = {"Authorization": "Bearer tok-dev1"}
    env = client.get("/api/v1/device/dev1/models/micro_speech", headers=auth).json()
    assert _verify(pub, env["manifest"].encode(), env["sig"], tmp_path)
    manifest = json.loads(env["manifest"])
    assert manifest["version"] == 2 and manifest["labels"][2] == "yes"

    blob = client.get("/api/v1/device/dev1/models/micro_speech/blob", headers=auth)
    assert blob.status_code == 200 and blob.content == _blob("micro_speech")
    assert blob.headers["content-length"] == str(manifest["bytes"])

    # Other owner's device, wrong token, unknown model.
    bob = {"Authorization": "Bearer tok-dev2"}
    assert client.get("/api/v1/device/dev2/models/micro_speech", headers=bob).status_code == 404
    assert client.get("/api/v1/device/dev1/models/micro_speech", headers=bob).status_code == 401
    assert client.get("/api/v1/device/dev1/models/nope", headers=auth).status_code == 404

    r = client.delete("/api/ml/models/micro_speech", headers={"X-Test-User": "alice@x.io"})
    assert r.status_code == 200
    assert client.get("/api/v1/device/dev1/models/micro_speech", headers=auth).status_code == 404


def test_upload_rejections(client):
    assert _upload(client, "ms_frontend", blob=b"not a model").status_code == 422
    big = b"\x00" * (ml_registry.MAX_MODEL_BYTES + 1)
    assert _upload(client, "ms_frontend", blob=big).status_code == 413
    r = client.post(
        "/api/ml/models",
        headers={"X-Test-User": "alice@x.io"},
        files={"file": ("m.tflite", _blob("ms_frontend"))},
        data={"meta": "{"},
    )
    assert r.status_code == 400
    assert client.get("/api/ml/models").status_code == 401


def test_missing_key_is_503(client, monkeypatch, tmp_path):
    monkeypatch.setenv("EPD_ML_SIGNING_KEY", str(tmp_path / "absent.pem"))
    # Key path is read when the router is built; rebuild through the fixture's app.
    app = client.app
    app.router.routes.clear()
    app.include_router(
        ml_registry.make_router(
            require_user=lambda: {"email": "alice@x.io"},
            require_device=lambda device_id: device_id,
            db=lambda: None,
            data_dir=tmp_path / "other",
        )
    )
    assert _upload(client, "ms_frontend").status_code == 503
