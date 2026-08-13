#!/bin/bash
# Resume PlatformIO dependency downloads overnight, then install packages.
set -u
cd "$HOME/.platformio/.cache/downloads" || exit 1
LOG="$HOME/Documents/esp32/scripts/overnight_pio_deps.log"
exec >>"$LOG" 2>&1

echo "==== $(date) overnight deps start ===="

download_one() {
  local name="$1" file="$2" url="$3" expected="$4"
  echo "[$(date)] ensure $name ($expected bytes) -> $file"
  local tries=0
  while true; do
    local sz=0
    [[ -f "$file" ]] && sz=$(stat -f%z "$file")
    if [[ "$sz" -eq "$expected" ]]; then
      echo "[$(date)] $name complete ($sz)"
      return 0
    fi
    tries=$((tries + 1))
    echo "[$(date)] $name attempt $tries size=$sz/$expected"
    # Avoid fighting an existing curl for the same file
    if pgrep -f "curl .*${file}" >/dev/null 2>&1; then
      echo "[$(date)] existing curl for $file; wait 60s"
      sleep 60
      continue
    fi
    curl -L --retry 30 --retry-delay 10 --retry-all-errors \
      --connect-timeout 30 -C - -o "$file" "$url"
    local rc=$?
    echo "[$(date)] curl exit=$rc"
    sz=$(stat -f%z "$file" 2>/dev/null || echo 0)
    if [[ "$sz" -eq "$expected" ]]; then
      echo "[$(date)] $name complete"
      return 0
    fi
    sleep 15
  done
}

install_pkg() {
  local name="$1" version="$2" tar="$3" owner="$4"
  local pkgdir="$HOME/.platformio/packages/$name"
  echo "[$(date)] install $name@$version"
  rm -rf "$pkgdir"
  mkdir -p "$pkgdir"
  tar -xzf "$tar" -C "$pkgdir"
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
print("installed", name, "entries", sorted(os.listdir(pkg))[:12])
PY
}

FW_FILE="framework-arduinoespressif32-3.20017.0.tar.gz"
FW_URL="https://dl.registry.platformio.org/download/platformio/tool/framework-arduinoespressif32/3.20017.0/framework-arduinoespressif32-3.20017.0.tar.gz"
FW_SIZE=246353348

RV_FILE="toolchain-riscv32-esp-darwin_arm64-12.2.0+20230208.tar.gz"
RV_URL="https://dl.registry.platformio.org/download/espressif/tool/toolchain-riscv32-esp/12.2.0+20230208/toolchain-riscv32-esp-darwin_arm64-12.2.0+20230208.tar.gz"
RV_SIZE=249455329

download_one "framework-arduinoespressif32" "$FW_FILE" "$FW_URL" "$FW_SIZE"
install_pkg "framework-arduinoespressif32" "3.20017.0" "$FW_FILE" "platformio"

download_one "toolchain-riscv32-esp" "$RV_FILE" "$RV_URL" "$RV_SIZE"
install_pkg "toolchain-riscv32-esp" "12.2.0+20230208" "$RV_FILE" "espressif"

echo "==== $(date) packages now: ===="
ls -la "$HOME/.platformio/packages"
echo "==== $(date) overnight deps done ===="
echo READY > "$HOME/Documents/esp32/scripts/overnight_pio_deps.ready"
