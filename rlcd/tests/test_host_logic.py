"""Compile and run the firmware's pure C++ logic on the host.

Covers rlcd/src/claude_proto.cpp (Claude Hardware Buddy protocol) and
rlcd/include/oc_battery.h (battery badge). Needs a C++17 compiler and the
ArduinoJson copy PlatformIO fetched into rlcd/.pio/libdeps.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RLCD = Path(__file__).resolve().parents[1]


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
                "-o",
                str(exe),
            ],
            check=True,
        )
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        assert run.stdout.strip() == "ok"


if __name__ == "__main__":
    test_host_logic()
    print("ok")
    sys.exit(0)
