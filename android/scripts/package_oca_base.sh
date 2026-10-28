#!/usr/bin/env bash
# Build the unsigned release APK and copy it to server/oca/ as the base for
# per-phone install packages (server/oca_pack.py, ADR 0009).
#
# Usage:
#   bash android/scripts/package_oca_base.sh
#   OC_OCA_DIR=/var/lib/onlyclaws/oca bash android/scripts/package_oca_base.sh
#
# Needs JDK 17, Gradle and the Android SDK (see android/README.md). The server
# signs each download; this script never signs and never adds a session.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ANDROID="$ROOT/android"
OUT="${OC_OCA_DIR:-$ROOT/server/oca}"
GRADLE="${GRADLE:-gradle}"

(cd "$ANDROID" && "$GRADLE" --quiet assembleRelease)

APK="$ANDROID/app/build/outputs/apk/release/app-release-unsigned.apk"
if [[ ! -f "$APK" ]]; then
  echo "missing $APK" >&2
  exit 1
fi
if unzip -l "$APK" | grep -q 'assets/session.json'; then
  echo "refusing: $APK already contains assets/session.json" >&2
  exit 1
fi

VERSION="$(sed -n 's/.*versionName *= *"\([^"]*\)".*/\1/p' "$ANDROID/app/build.gradle.kts" | head -n 1)"
mkdir -p "$OUT"
cp "$APK" "$OUT/oca-base.apk.tmp"
mv "$OUT/oca-base.apk.tmp" "$OUT/oca-base.apk"
echo "${VERSION:-unknown}" > "$OUT/VERSION"
echo "packaged $OUT/oca-base.apk (version ${VERSION:-unknown})"
