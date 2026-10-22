#!/usr/bin/env bash
# Generate the Ed25519 key the control plane uses to sign Lua scripts.
# Prints the hex public key to paste into OC_SCRIPT_PUBKEY_HEX
# (rlcd/include/cloud_config.h). The PEM stays out of git (server/data/).
set -euo pipefail
OUT="${1:-server/data/script_signing_key.pem}"
mkdir -p "$(dirname "$OUT")"
openssl genpkey -algorithm ED25519 -out "$OUT"
chmod 600 "$OUT"
echo "wrote $OUT"
echo -n "OC_SCRIPT_PUBKEY_HEX "
openssl pkey -in "$OUT" -pubout -outform DER | python3 -c 'import sys; print(sys.stdin.buffer.read()[-32:].hex())'
