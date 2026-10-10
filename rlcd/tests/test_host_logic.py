"""Compile and run the firmware's pure C++ logic on the host.

Covers rlcd/src/claude_proto.cpp (Claude Hardware Buddy protocol),
rlcd/include/oc_battery.h (battery badge) and rlcd/src/ml_manifest.cpp (model
manifest), including a manifest built by server/ml_registry.py. Needs a C++17 compiler and the
ArduinoJson copy PlatformIO fetched into rlcd/.pio/libdeps.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RLCD = Path(__file__).resolve().parents[1]
ROOT = RLCD.parent


def _server_manifest(out: Path) -> Path:
    """micro_speech manifest exactly as the control plane would sign it."""
    sys.path.insert(0, str(ROOT / "server"))
    import json

    import ml_registry

    models = ROOT / "ml" / "models" / "micro_speech"
    meta = json.loads((models / "micro_speech.meta.json").read_text())
    blob = (models / "micro_speech.tflite").read_bytes()
    out.write_bytes(ml_registry.manifest_bytes(ml_registry.build_manifest(meta, blob, 1)))
    return out


def _arduinojson_include() -> Path | None:
    for lib in sorted((RLCD / ".pio" / "libdeps").glob("*/ArduinoJson/src")):
        if (lib / "ArduinoJson.h").exists():
            return lib
    return None


def test_host_logic() -> None:
    cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    aj = _arduinojson_include()
    if not cxx or not aj:
        try:
            import pytest

            pytest.skip("need a C++ compiler and `pio run` (ArduinoJson in .pio/libdeps)")
        except ImportError:
            print("skip: no compiler or ArduinoJson")
            return
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "host_logic"
        subprocess.run(
            [
                cxx,
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-I",
                str(RLCD / "include"),
                "-I",
                str(aj),
                str(RLCD / "tests" / "host_logic_test.cpp"),
                str(RLCD / "src" / "claude_proto.cpp"),
                str(RLCD / "src" / "ml_manifest.cpp"),
                "-o",
                str(exe),
            ],
            check=True,
        )
        manifest = _server_manifest(Path(tmp) / "manifest.json")
        run = subprocess.run([str(exe), str(manifest)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        assert run.stdout.strip() == "ok"


if __name__ == "__main__":
    test_host_logic()
    print("ok")
    sys.exit(0)
