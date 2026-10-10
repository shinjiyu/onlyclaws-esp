"""On-device model registry: agents upload .tflite, devices fetch signed manifests.

Agent side (session or oct_ token):
  POST   /api/ml/models          multipart: file=<.tflite>, meta=<json>
  GET    /api/ml/models
  DELETE /api/ml/models/{name}
  GET    /api/ml/opset
Device side (device bearer; models of the device's owner):
  GET /api/v1/device/{id}/models/{name}       {"manifest": "<json>", "sig": "<b64 DER>"}
  GET /api/v1/device/{id}/models/{name}/blob  raw .tflite

Every upload is parsed as a TFLite flatbuffer and refused if it uses an op
outside the firmware op set. The manifest bytes are signed with ECDSA P-256
(openssl); firmware verifies against OC_ML_PUBKEY_PEM before trusting the
sha256 that pins the blob. Format: doc/structurizr/ML-PLUGIN.md.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

import ml_opset
import tenancy

MAX_MODEL_BYTES = 2 * 1024 * 1024
MAX_ARENA_KB = 1024
MAX_MODELS_PER_OWNER = 32
MAX_LABELS = 64
MAX_LABEL_LEN = 32
MIC_RATE = 16000
KINDS = ("audio", "tensor", "frontend")
NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


class TfliteError(ValueError):
    pass


# ---- minimal TFLite flatbuffer reader (Model.operator_codes only) ----


def _read(fmt: str, buf: bytes, pos: int) -> int:
    if pos < 0 or pos + struct.calcsize(fmt) > len(buf):
        raise TfliteError("truncated flatbuffer")
    return struct.unpack_from(fmt, buf, pos)[0]


def _u32(buf: bytes, pos: int) -> int:
    return _read("<I", buf, pos)


def _field(buf: bytes, table: int, index: int) -> Optional[int]:
    """Absolute position of field `index` in the table at `table`, or None if absent."""
    vtable = table - _read("<i", buf, table)
    vsize = _read("<H", buf, vtable)
    slot = 4 + 2 * index
    if slot + 2 > vsize:
        return None
    off = _read("<H", buf, vtable + slot)
    return table + off if off else None


def _deref(buf: bytes, pos: int) -> int:
    return pos + _u32(buf, pos)


def _vector(buf: bytes, pos: int) -> tuple[int, int]:
    start = _deref(buf, pos)
    n = _u32(buf, start)
    if n > len(buf):
        raise TfliteError("bad vector length")
    return start + 4, n


def tflite_op_codes(buf: bytes) -> tuple[set[int], set[str], int]:
    """(builtin codes, custom op names, schema version) declared by the model."""
    if len(buf) < 8 or buf[4:8] != b"TFL3":
        raise TfliteError("not a TFLite flatbuffer (missing TFL3 identifier)")
    model = _deref(buf, 0)
    vpos = _field(buf, model, 0)
    version = _u32(buf, vpos) if vpos is not None else 0
    codes_pos = _field(buf, model, 1)
    builtins: set[int] = set()
    customs: set[str] = set()
    if codes_pos is None:
        return builtins, customs, version
    first, n = _vector(buf, codes_pos)
    for i in range(n):
        code = _deref(buf, first + 4 * i)
        dep = _field(buf, code, 0)
        deprecated = _read("<b", buf, dep) if dep is not None else 0
        full = _field(buf, code, 3)
        builtin = _read("<i", buf, full) if full is not None else 0
        op = max(deprecated, builtin)
        if op == ml_opset.BUILTIN_CUSTOM:
            cpos = _field(buf, code, 1)
            if cpos is None:
                raise TfliteError("custom op without a name")
            s, ln = _vector(buf, cpos)
            if s + ln > len(buf):
                raise TfliteError("truncated custom op name")
            customs.add(buf[s : s + ln].decode("utf-8", "replace"))
        else:
            builtins.add(op)
    return builtins, customs, version


def check_opset(buf: bytes, opset: int = ml_opset.OPSET_VERSION) -> None:
    builtins, customs, version = tflite_op_codes(buf)
    if version != 3:
        raise TfliteError(f"TFLite schema version {version}, firmware needs 3")
    allowed_b, allowed_c = ml_opset.OPSETS[opset]
    names = {v: k for k, v in ml_opset.BUILTINS_V1.items()}
    bad = sorted(names.get(b, f"builtin#{b}") for b in builtins - allowed_b)
    bad += sorted(customs - allowed_c)
    if bad:
        raise TfliteError(f"ops outside firmware op set {opset}: {', '.join(bad)}")


# ---- manifest ----


def _int(meta: dict[str, Any], key: str, lo: int, hi: int) -> int:
    v = meta.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise HTTPException(status_code=400, detail=f"{key} must be an integer in [{lo}, {hi}]")
    return v


def build_manifest(meta: dict[str, Any], blob: bytes, version: int) -> dict[str, Any]:
    """Validate agent-supplied meta (same rules as rlcd/src/ml_manifest.cpp)."""
    name = meta.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="name must match [a-z0-9_-]{1,32}")
    kind = meta.get("kind")
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {KINDS}")
    labels = meta.get("labels") or []
    if not isinstance(labels, list) or len(labels) > MAX_LABELS:
        raise HTTPException(status_code=400, detail=f"labels must be a list of <= {MAX_LABELS}")
    for label in labels:
        if not isinstance(label, str) or len(label) > MAX_LABEL_LEN:
            raise HTTPException(status_code=400, detail=f"labels must be strings <= {MAX_LABEL_LEN}")
    out: dict[str, Any] = {
        "name": name,
        "version": version,
        "opset": ml_opset.OPSET_VERSION,
        "kind": kind,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob),
        "arena_kb": _int(meta, "arena_kb", 1, MAX_ARENA_KB),
        "labels": labels,
    }
    if kind == "audio":
        a = meta.get("audio")
        if not isinstance(a, dict):
            raise HTTPException(status_code=400, detail="audio models need an audio spec")
        if a.get("rate", MIC_RATE) != MIC_RATE:
            raise HTTPException(status_code=400, detail="audio rate must be 16000")
        spec = {
            "rate": MIC_RATE,
            "window_ms": _int(a, "window_ms", 1, 1000),
            "stride_ms": _int(a, "stride_ms", 1, 1000),
            "frames": _int(a, "frames", 1, 500),
            "features": _int(a, "features", 1, 512),
            "frontend": a.get("frontend"),
        }
        fe = spec["frontend"]
        if not isinstance(fe, str) or not NAME_RE.match(fe) or fe == name:
            raise HTTPException(status_code=400, detail="audio.frontend must name another model")
        win = MIC_RATE * spec["window_ms"] // 1000
        stride = MIC_RATE * spec["stride_ms"] // 1000
        if (spec["frames"] - 1) * stride + win > 10 * MIC_RATE:
            raise HTTPException(status_code=400, detail="audio clip longer than 10 s")
        out["audio"] = spec
    return out


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sign(data: bytes, key_path: Path) -> str:
    """Base64 DER ECDSA-SHA256 signature of `data`."""
    if not key_path.is_file():
        raise HTTPException(status_code=503, detail="model signing key not configured on server")
    proc = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(key_path)],
        input=data,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise HTTPException(status_code=500, detail="model signing failed")
    return base64.b64encode(proc.stdout).decode()


# ---- storage ----


class Store:
    """<data>/ml/<owner key>/<name>.{tflite,manifest.json,sig}"""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()

    def owner_dir(self, email: str) -> Path:
        key = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]
        return self.root / key

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def manifest(self, email: str, name: str) -> Optional[dict[str, Any]]:
        p = self.owner_dir(email) / f"{name}.manifest.json"
        if not p.is_file():
            return None
        return json.loads(p.read_bytes())

    def envelope(self, email: str, name: str) -> Optional[dict[str, str]]:
        d = self.owner_dir(email)
        m, s = d / f"{name}.manifest.json", d / f"{name}.sig"
        if not m.is_file() or not s.is_file():
            return None
        return {"manifest": m.read_text(), "sig": s.read_text().strip()}

    def blob(self, email: str, name: str) -> Optional[bytes]:
        p = self.owner_dir(email) / f"{name}.tflite"
        return p.read_bytes() if p.is_file() else None

    def names(self, email: str) -> list[str]:
        d = self.owner_dir(email)
        if not d.is_dir():
            return []
        return sorted(p.name[: -len(".manifest.json")] for p in d.glob("*.manifest.json"))

    def put(self, email: str, manifest: dict[str, Any], blob: bytes, key: Path) -> dict[str, Any]:
        d = self.owner_dir(email)
        d.mkdir(parents=True, exist_ok=True)
        name = manifest["name"]
        raw = manifest_bytes(manifest)
        sig = sign(raw, key)
        # Blob first: a device holding the old manifest still finds a sha256 mismatch,
        # never a manifest pointing at a missing blob.
        self._write(d / f"{name}.tflite", blob)
        self._write(d / f"{name}.manifest.json", raw)
        self._write(d / f"{name}.sig", sig.encode())
        return manifest

    def delete(self, email: str, name: str) -> bool:
        d = self.owner_dir(email)
        found = False
        for suffix in (".manifest.json", ".sig", ".tflite"):
            p = d / f"{name}{suffix}"
            if p.is_file():
                p.unlink()
                found = True
        return found


def make_router(
    *,
    require_user: Callable[..., Any],
    require_device: Callable[..., Any],
    db: Callable[[], Any],
    data_dir: Path,
) -> APIRouter:
    store = Store(data_dir / "ml")
    key_path = Path(os.environ.get("EPD_ML_SIGNING_KEY", str(data_dir / "ml_signing_key.pem")))
    router = APIRouter(tags=["ml"])

    def device_owner(device_id: str) -> str:
        with db() as conn:
            row = tenancy.get_device(conn, (device_id or "").strip().lower())
        owner = (row["owner_email"] or "").strip().lower() if row is not None else ""
        if not owner:
            raise HTTPException(status_code=404, detail="device has no owner")
        return owner

    @router.get("/api/ml/opset")
    async def ml_opset_info(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return ml_opset.describe()

    @router.get("/api/ml/models")
    async def ml_list(sess: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        email = tenancy.session_email(sess)
        return {"models": [store.manifest(email, n) for n in store.names(email)]}

    @router.post("/api/ml/models")
    async def ml_upload(
        file: UploadFile = File(...),
        meta: str = Form(...),
        sess: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        email = tenancy.session_email(sess)
        try:
            meta_obj = json.loads(meta)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"meta is not JSON: {e}") from e
        if not isinstance(meta_obj, dict):
            raise HTTPException(status_code=400, detail="meta must be a JSON object")
        blob = await file.read(MAX_MODEL_BYTES + 1)
        if not blob or len(blob) > MAX_MODEL_BYTES:
            raise HTTPException(status_code=413, detail=f"model must be 1..{MAX_MODEL_BYTES} bytes")
        try:
            check_opset(blob)
        except TfliteError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        with store.lock:
            prev = store.manifest(email, str(meta_obj.get("name", "")))
            if prev is None and len(store.names(email)) >= MAX_MODELS_PER_OWNER:
                raise HTTPException(status_code=409, detail="model limit reached; delete one first")
            manifest = build_manifest(meta_obj, blob, (prev or {}).get("version", 0) + 1)
            if manifest["kind"] == "audio":
                fe = store.manifest(email, manifest["audio"]["frontend"])
                if not fe or fe.get("kind") != "frontend":
                    raise HTTPException(
                        status_code=400,
                        detail="upload the audio.frontend model (kind=frontend) first",
                    )
            return store.put(email, manifest, blob, key_path)

    @router.delete("/api/ml/models/{name}")
    async def ml_delete(name: str, sess: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        if not NAME_RE.match(name):
            raise HTTPException(status_code=400, detail="bad model name")
        with store.lock:
            if not store.delete(tenancy.session_email(sess), name):
                raise HTTPException(status_code=404, detail="no such model")
        return {"deleted": name}

    @router.get("/api/v1/device/{device_id}/models/{name}")
    async def ml_device_envelope(
        device_id: str, name: str, _: str = Depends(require_device)
    ) -> JSONResponse:
        if not NAME_RE.match(name):
            raise HTTPException(status_code=400, detail="bad model name")
        env = store.envelope(device_owner(device_id), name)
        if env is None:
            raise HTTPException(status_code=404, detail="no such model")
        return JSONResponse(env, headers={"Cache-Control": "no-store"})

    @router.get("/api/v1/device/{device_id}/models/{name}/blob")
    async def ml_device_blob(
        device_id: str, name: str, _: str = Depends(require_device)
    ) -> Response:
        if not NAME_RE.match(name):
            raise HTTPException(status_code=400, detail="bad model name")
        blob = store.blob(device_owner(device_id), name)
        if blob is None:
            raise HTTPException(status_code=404, detail="no such model")
        return Response(
            content=blob,
            media_type="application/octet-stream",
            headers={"Cache-Control": "no-store"},
        )

    return router
