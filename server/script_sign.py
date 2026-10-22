"""Ed25519 envelopes for Lua scripts persisted on the device.

The byte layout matches ``rlcd/include/script_store.h`` (magic ``LCLW``,
header, source, 64-byte signature over the header and source). The device
rebuilds that prefix from the JSON fields and checks the signature before
anything is written to flash.
"""

from __future__ import annotations

import base64
import hashlib
import re
import struct
import subprocess
import tempfile
from pathlib import Path

HEADER = 83
MAGIC = b"LCLW"
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_SOURCE = 24000


class ScriptSignError(Exception):
    pass


def next_version(previous: object) -> int:
    try:
        n = int(previous or 0)
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    if n >= 0xFFFFFFFF:
        raise ScriptSignError("script version exhausted")
    return n + 1


def build_prefix(script_id: str, source: str, mode: str, every_ms: int, version: int) -> bytes:
    if not isinstance(script_id, str) or not NAME_RE.match(script_id):
        raise ScriptSignError("bad script id")
    if mode not in ("once", "loop"):
        raise ScriptSignError("bad script mode")
    if not isinstance(every_ms, int) or isinstance(every_ms, bool) or every_ms < 0 or every_ms > 3_600_000:
        raise ScriptSignError("bad every_ms")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1 or version > 0xFFFFFFFF:
        raise ScriptSignError("bad script version")
    if not isinstance(source, str):
        raise ScriptSignError("bad script length")
    raw = source.encode("utf-8")
    if not raw or len(raw) > MAX_SOURCE:
        raise ScriptSignError("bad script length")
    buf = bytearray(HEADER + len(raw))
    buf[0:4] = MAGIC
    buf[4] = 1
    buf[5 : 5 + len(script_id)] = script_id.encode("ascii")
    buf[37] = 1 if mode == "once" else 2
    struct.pack_into("<I", buf, 39, every_ms)
    struct.pack_into("<I", buf, 43, len(raw))
    struct.pack_into("<I", buf, 47, version)
    buf[51:83] = hashlib.sha256(raw).digest()
    buf[HEADER:] = raw
    return bytes(buf)


def sign_prefix(prefix: bytes, key_path: Path) -> bytes:
    if not key_path.is_file():
        raise FileNotFoundError(key_path)
    # OpenSSL refuses a raw Ed25519 sign on a pipe: it needs the input length.
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "prefix.bin"
        dst = Path(tmp) / "sig.bin"
        src.write_bytes(prefix)
        proc = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(key_path),
                "-rawin",
                "-in",
                str(src),
                "-out",
                str(dst),
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        sig = dst.read_bytes() if dst.is_file() else b""
    if proc.returncode != 0 or len(sig) != 64:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ScriptSignError(err[-1] if err else "script signing failed")
    return sig


def signed_script_fields(
    *,
    script_id: str,
    source: str,
    mode: str,
    every_ms: int,
    version: int,
    key_path: Path,
) -> dict[str, object]:
    prefix = build_prefix(script_id, source, mode, every_ms, version)
    sig = sign_prefix(prefix, key_path)
    return {
        "version": version,
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "sig": base64.b64encode(sig).decode("ascii"),
    }


def signed_blob(
    *,
    script_id: str,
    source: str,
    mode: str,
    every_ms: int,
    version: int,
    key_path: Path,
) -> bytes:
    prefix = build_prefix(script_id, source, mode, every_ms, version)
    return prefix + sign_prefix(prefix, key_path)


def raw_public_key(key_path: Path) -> bytes:
    """32-byte Ed25519 public key from a PEM private or public key."""
    proc = subprocess.run(
        ["openssl", "pkey", "-in", str(key_path), "-pubout", "-outform", "DER"],
        capture_output=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0 or len(proc.stdout) < 32:
        raise ScriptSignError("could not read script public key")
    raw = proc.stdout[-32:]
    if proc.stdout[:12] != bytes.fromhex("302a300506032b6570032100"):
        raise ScriptSignError("unexpected Ed25519 public key encoding")
    return raw
