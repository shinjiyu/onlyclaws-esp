"""Host build of the script store, plus the control-plane envelope it must open.

Also checks the partition tables: LittleFS is a data partition and does not
overlap an OTA app slot.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

RLCD = Path(__file__).resolve().parents[1]
ROOT = RLCD.parent
sys.path.insert(0, str(ROOT / "server"))

import script_sign  # noqa: E402


def _parts(path: Path) -> list[tuple[str, str, int, int]]:
    out = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        cells = [c.strip() for c in line.split(",")]
        name, typ, _sub, off, size = cells[:5]
        out.append((name, typ, int(off, 16), int(size, 16)))
    return out


def _assert_layout(path: Path, flash_end: int, *, dual_ota: bool) -> None:
    parts = _parts(path)
    names = [p[0] for p in parts]
    assert "littlefs" in names
    assert "app0" in names
    assert ("app1" in names) is dual_ota
    spans = []
    for name, typ, off, size in parts:
        assert off >= 0x9000 and off + size <= flash_end, name
        if name == "littlefs":
            assert typ == "data"
            assert size >= 0x20000
        if name in ("app0", "app1"):
            assert typ == "app"
        spans.append((off, off + size, name))
    spans.sort()
    for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
        assert a1 <= b0, f"{an} overlaps {bn}"
    little = next(p for p in parts if p[0] == "littlefs")
    for name, typ, off, size in parts:
        if typ != "app":
            continue
        assert little[2] + little[3] <= off or off + size <= little[2]


def test_partition_tables_keep_littlefs_beside_ota():
    _assert_layout(RLCD / "partitions_16MB.csv", 0x1000000, dual_ota=True)
    _assert_layout(RLCD / "partitions_4MB.csv", 0x400000, dual_ota=False)
    ini = (RLCD / "platformio.ini").read_text()
    assert "partitions_16MB.csv" in ini
    assert "partitions_4MB.csv" in ini
    # ML cache partition is unchanged from Arduino default_16MB.csv.
    spiffs = next(p for p in _parts(RLCD / "partitions_16MB.csv") if p[0] == "spiffs")
    assert (spiffs[2], spiffs[3]) == (0xC90000, 0x360000)


def _cxx() -> str:
    import shutil

    # `c++` may be clang without the C++ standard library headers.
    return shutil.which("g++") or shutil.which("clang++") or shutil.which("c++") or ""


def _build(tmp: Path) -> Path:
    cxx = _cxx()
    assert cxx, "need a C++ compiler"
    exe = tmp / "script_store"
    nacl = tmp / "tweetnacl.o"
    subprocess.run(
        [
            "cc",
            "-c",
            "-O2",
            "-I",
            str(RLCD / "third_party" / "tweetnacl"),
            str(RLCD / "third_party" / "tweetnacl" / "tweetnacl.c"),
            "-o",
            str(nacl),
        ],
        check=True,
    )
    subprocess.run(
        [
            cxx,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-I",
            str(RLCD / "include"),
            str(RLCD / "tests" / "test_script_store.cpp"),
            str(RLCD / "src" / "script_store.cpp"),
            str(nacl),
            "-o",
            str(exe),
        ],
        check=True,
    )
    return exe


def test_host_store_and_openssl_envelope():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        exe = _build(tmp_path)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        assert run.stdout.strip() == "ok"

        key = tmp_path / "key.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
            check=True,
            capture_output=True,
        )
        pub = script_sign.raw_public_key(key)
        script_id = "a" * 32
        source = "function on_start() end\n"
        blob = script_sign.signed_blob(
            script_id=script_id,
            source=source,
            mode="loop",
            every_ms=1000,
            version=7,
            key_path=key,
        )
        prefix = script_sign.build_prefix(script_id, source, "loop", 1000, 7)
        sig = blob[len(prefix) :]
        assert len(sig) == 64 and blob.startswith(prefix)
        (tmp_path / "sig").write_bytes(sig)
        (tmp_path / "prefix").write_bytes(prefix)
        pub_pem = tmp_path / "pub.pem"
        subprocess.run(
            ["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(pub_pem)],
            check=True,
            capture_output=True,
        )
        verified = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(pub_pem),
                "-rawin",
                "-sigfile",
                str(tmp_path / "sig"),
                "-in",
                str(tmp_path / "prefix"),
            ],
            capture_output=True,
        )
        assert verified.returncode == 0, verified.stderr

        (tmp_path / "pub.bin").write_bytes(pub)
        (tmp_path / "blob.bin").write_bytes(blob)
        opened = subprocess.run(
            [str(exe), str(tmp_path / "pub.bin"), str(tmp_path / "blob.bin")],
            capture_output=True,
            text=True,
        )
        assert opened.returncode == 0, opened.stderr
        assert opened.stdout.strip() == f"ok {script_id} 7"

        bad = bytearray(blob)
        bad[script_sign.HEADER + 5] ^= 0x01
        (tmp_path / "bad.bin").write_bytes(bad)
        rejected = subprocess.run(
            [str(exe), str(tmp_path / "pub.bin"), str(tmp_path / "bad.bin")],
            capture_output=True,
            text=True,
        )
        assert rejected.returncode != 0
