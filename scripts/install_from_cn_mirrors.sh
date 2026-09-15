#!/usr/bin/env bash
# Install ESP32 toolchains from Espressif CN CDN + Arduino core via gh-proxy.
set -euo pipefail
CACHE="${HOME}/.platformio/.cache/cn"
PKGS="${HOME}/.platformio/packages"
mkdir -p "$CACHE" "$PKGS"

write_piopm() {
  local name="$1" version="$2" owner="$3" pkgdir="$4" ptype="$5"
  python3 - "$name" "$version" "$owner" "$pkgdir" "$ptype" <<'PY'
import json, os, sys
name, version, owner, pkg, ptype = sys.argv[1:6]
meta = {
    "name": name,
    "version": version,
    "spec": {"owner": owner, "name": name, "requirements": version, "uri": None},
    "type": [ptype],
}
pj = os.path.join(pkg, "package.json")
if not os.path.exists(pj):
    json.dump({"name": name, "version": version}, open(pj, "w"), indent=2)
json.dump(meta, open(os.path.join(pkg, ".piopm"), "w"))
print("installed", name, version, "top=", sorted(os.listdir(pkg))[:10])
PY
}

flatten_single_dir() {
  local pkgdir="$1"
  local kids=()
  local d
  for d in "$pkgdir"/*; do
    [[ -e "$d" ]] || continue
    kids+=("$d")
  done
  if [[ ${#kids[@]} -eq 1 && -d "${kids[0]}" ]]; then
    local tmp="$pkgdir/.flatten.$$"
    mv "${kids[0]}" "$tmp"
    shopt -s dotglob
    mv "$tmp"/* "$pkgdir"/
    shopt -u dotglob
    rm -rf "$tmp"
  fi
}

install_xz() {
  local name="$1" version="$2" tar="$3"
  local pkgdir="$PKGS/$name"
  echo "extract $tar -> $pkgdir"
  rm -rf "$pkgdir"
  mkdir -p "$pkgdir"
  tar -xJf "$CACHE/$tar" -C "$pkgdir"
  flatten_single_dir "$pkgdir"
  write_piopm "$name" "$version" "espressif" "$pkgdir" "tool"
}

install_arduino() {
  local tar="$CACHE/arduino-esp32-2.0.17.tar.gz"
  if ! gzip -t "$tar" 2>/dev/null; then
    echo "SKIP arduino core: archive incomplete ($tar)"
    return 0
  fi
  local pkgdir="$PKGS/framework-arduinoespressif32"
  echo "extract $tar -> $pkgdir"
  rm -rf "$pkgdir"
  mkdir -p "$pkgdir"
  tar -xzf "$tar" -C "$pkgdir"
  flatten_single_dir "$pkgdir"
  write_piopm "framework-arduinoespressif32" "2.0.17" "platformio" "$pkgdir" "framework"
}

install_xz toolchain-riscv32-esp "12.2.0+20230208" \
  riscv32-esp-elf-12.2.0_20230208-aarch64-apple-darwin.tar.xz
install_xz toolchain-xtensa-esp32s3 "12.2.0+20230208" \
  xtensa-esp32s3-elf-12.2.0_20230208-aarch64-apple-darwin.tar.xz
install_xz toolchain-xtensa-esp32 "12.2.0+20230208" \
  xtensa-esp32-elf-12.2.0_20230208-aarch64-apple-darwin.tar.xz
install_arduino

echo "done. packages:"
ls "$PKGS"
