#!/usr/bin/env bash
# Package a PlatformIO env into server/firmware/<product>/ for /flash (ESP Web Tools).
#
# Usage:
#   bash rlcd/scripts/package_web_flash.sh                  # default: esp32-s3-amoled-175c
#   bash rlcd/scripts/package_web_flash.sh esp32-s3-amoled-175c 0.21.0
#   bash rlcd/scripts/package_web_flash.sh all              # every built env under .pio/build
#   OC_FIRMWARE_DIR=/var/lib/onlyclaws/firmware bash rlcd/scripts/package_web_flash.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RLCD="$ROOT/rlcd"
OUT_ROOT="${OC_FIRMWARE_DIR:-$ROOT/server/firmware}"
DEFAULT_ENV="esp32-c3-folo-passport"
VERSION_ARG="${2:-}"

map_env_to_id() {
  case "$1" in
    esp32-s3-rlcd-42|esp32-s3-epaper-397|esp32-s3-bare|esp32-roarm-m2|esp32-s3-amoled-175c|esp32-c3-folo-passport) echo "$1" ;;
    *) echo "" ;;
  esac
}

find_boot_app0() {
  local build="$1"
  if [[ -f "$build/boot_app0.bin" ]]; then
    echo "$build/boot_app0.bin"
    return
  fi
  local cand
  cand="$(find "${HOME}/.platformio/packages" -name boot_app0.bin 2>/dev/null | head -n 1 || true)"
  if [[ -n "$cand" && -f "$cand" ]]; then
    echo "$cand"
    return
  fi
  echo ""
}

package_one() {
  local env="$1"
  local id
  id="$(map_env_to_id "$env")"
  if [[ -z "$id" ]]; then
    echo "unknown env: $env" >&2
    return 1
  fi

  local build="$RLCD/.pio/build/$env"
  if [[ ! -f "$build/firmware.bin" ]]; then
    echo "missing $build/firmware.bin — run: (cd rlcd && pio run -e $env)" >&2
    return 1
  fi
  if [[ ! -f "$build/bootloader.bin" || ! -f "$build/partitions.bin" ]]; then
    echo "missing bootloader/partitions in $build" >&2
    return 1
  fi

  local boot0
  boot0="$(find_boot_app0 "$build")"
  if [[ -z "$boot0" ]]; then
    echo "boot_app0.bin not found (PlatformIO packages or build dir)" >&2
    return 1
  fi

  local dest="$OUT_ROOT/$id"
  mkdir -p "$dest"
  cp -f "$build/bootloader.bin" "$dest/bootloader.bin"
  cp -f "$build/partitions.bin" "$dest/partitions.bin"
  cp -f "$boot0" "$dest/boot_app0.bin"
  cp -f "$build/firmware.bin" "$dest/firmware.bin"

  local ver="$VERSION_ARG"
  if [[ -z "$ver" ]]; then
    ver="$(date -u +%Y%m%d)"
  fi
  printf '%s\n' "$ver" >"$dest/VERSION"

  (
    cd "$ROOT/server"
    python3 - <<PY
from firmware_catalog import write_static_manifest
write_static_manifest("$id")
print("wrote manifest for $id")
PY
  )

  echo "packaged $id → $dest (version $ver)"
}

main() {
  local target="${1:-$DEFAULT_ENV}"
  if [[ "$target" == "all" ]]; then
    local e
    for e in esp32-c3-folo-passport esp32-s3-amoled-175c esp32-s3-rlcd-42 esp32-s3-epaper-397 esp32-s3-bare esp32-roarm-m2; do
      if [[ -f "$RLCD/.pio/build/$e/firmware.bin" ]]; then
        package_one "$e" || true
      else
        echo "skip $e (not built)"
      fi
    done
  else
    package_one "$target"
  fi
}

main "$@"
