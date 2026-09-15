#!/usr/bin/env bash
# Install PlatformIO packages from already-downloaded tarballs in the cache.
set -euo pipefail
CACHE="${PLATFORMIO_CACHE:-$HOME/.platformio/.cache/downloads}"
PKGS="${PLATFORMIO_PKGS:-$HOME/.platformio/packages}"

install_one() {
  local name="$1" version="$2" tar="$3" owner="$4"
  local file="$CACHE/$tar"
  local sz expect
  case "$name" in
    framework-arduinoespressif32) expect=246353348 ;;
    toolchain-riscv32-esp) expect=249455329 ;;
    *) expect=0 ;;
  esac
  [[ -f "$file" ]] || { echo "missing $file"; return 1; }
  sz=$(stat -f%z "$file")
  if [[ "$expect" -gt 0 && "$sz" -ne "$expect" ]]; then
    echo "incomplete $tar size=$sz expect=$expect"; return 1
  fi
  local pkgdir="$PKGS/$name"
  echo "install $name@$version from $tar ($sz bytes)"
  rm -rf "$pkgdir"
  mkdir -p "$pkgdir"
  tar -xzf "$file" -C "$pkgdir"
  python3 - "$name" "$version" "$owner" "$pkgdir" <<'PY'
import json, os, sys
name, version, owner, pkg = sys.argv[1:5]
meta = {
    "name": name,
    "version": version,
    "spec": {"owner": owner, "name": name, "requirements": version, "uri": None},
    "type": ["tool"],
}
pj = os.path.join(pkg, "package.json")
if not os.path.exists(pj):
    json.dump({"name": name, "version": version}, open(pj, "w"), indent=2)
json.dump(meta, open(os.path.join(pkg, ".piopm"), "w"))
print("ok", name, "top=", sorted(os.listdir(pkg))[:8])
PY
}

install_one framework-arduinoespressif32 3.20017.0 \
  framework-arduinoespressif32-3.20017.0.tar.gz platformio
install_one toolchain-riscv32-esp "12.2.0+20230208" \
  toolchain-riscv32-esp-darwin_arm64-12.2.0+20230208.tar.gz espressif

echo "done. packages:"
ls "$PKGS"
