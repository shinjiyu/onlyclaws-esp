# Lua scripts survive power loss

A deployed script used to live only in RAM. Reboot or power loss dropped it, and the board waited for the cloud to send it again. The device now stores the last signed script on a LittleFS partition and loads it during boot, including when Wi-Fi is down.

## Partition

S3 products (`partitions_16MB.csv`) keep dual OTA slots. `app0` is the stock 6.25 MB slot. `app1` is 128 KB smaller so a 128 KB `littlefs` partition fits between the apps and the **unchanged** `spiffs` partition (the ML model cache). RoArm (`partitions_4MB.csv`) keeps the 3 MB `ota_0` slot from `huge_app.csv`; `littlefs` is carved out of the unused spiffs region. There is no second app slot on the 4 MB flash.

`littlefs` is a data partition. Its subtype is `spiffs` because that is the partition-table type LittleFS uses. The label is `littlefs`, mounted at `/littlefs` with `esp_vfs_littlefs_register`. That is a second filesystem beside the Arduino `LittleFS` object the ML plugin mounts on `spiffs` — the Arduino object can only mount one partition.

OTA and `pio run -t upload` write bootloader, the partition table, and an app slot. They do not erase `littlefs`. `rlcd/scripts/safe_upload_keep_nvs.sh` still refuses `erase_flash`. The firmware refuses to mount `littlefs` if that partition overlaps an app slot, and it never calls `esp_partition_erase` on it. The first boot of an empty or corrupt filesystem may format **that partition only**.

Flash the new table once (`pio run -t upload` does). After that, app updates leave the script files in place as long as this table stays put.

## Envelope

The control plane still accepts `POST /api/scripts` with Lua `source`. On deploy it assigns a monotonic `version` per device and signs an `LCLW` prefix with Ed25519 (`EPD_SCRIPT_SIGNING_KEY`, default `data/script_signing_key.pem`). The device message is the usual JSON plus `version`, `sha256`, and `sig`.

```
 0   4   "LCLW"
 4   1   format version 1
 5  32   script id, NUL-padded
37   1   1 = once, 2 = loop
38   1   flags (0)
39   4   every_ms, little-endian
43   4   content length
47   4   version
51  32   SHA-256 of the Lua bytes
83   N   Lua source
```

The 64-byte Ed25519 signature covers those bytes and is sent separately (`sig`, standard base64). The device rebuilds the prefix, checks the hash and the signature, and only then writes flash. A bad signature is dropped and is not stored.

The public key in the firmware is `OC_SCRIPT_PUBKEY_HEX` (`rlcd/include/cloud_config.h`). It is empty in a stock build, so the device refuses scripts until that hex matches the server PEM. Generate a pair with `bash scripts/gen_script_signing_key.sh`, paste the printed hex, and rebuild. Deploy returns 503 when the PEM is missing. Older firmware ignores the extra JSON fields and still runs `source` from RAM.

## On the device

Files live under `/littlefs/s/`:

- `s/<script_id>.<version>` — one envelope
- `s/index.json` — active id, run flag, and which versions are still valid

Writes go to a `.tmp` file, the bytes are read back, then `rename` publishes them. Replacing the index renames the previous file to `.bak` first and puts it back if the new rename fails. A leftover `.tmp` is deleted on the next boot and is never executed. The store keeps the last 3 versions of the one active script.

Boot loads the newest valid version and runs it. If that version fails verification or `scriptEngineLoadLua` fails, it is marked invalid and the previous version is tried. When none remain, the board enters safe mode: Wi-Fi and the cloud channel stay up, no script runs, and `/status` reports `meta.script_safe`. `POST /api/script/stop` clears the run flag so the next boot stays idle until a new deploy. A `once` script that finishes on its own is still restored after power loss.

While a restored script is running and the saved network is down, the firmware does not block in the setup portal. It keeps ticking the script and retries Wi-Fi in the background. A long-press of KEY still opens the portal.
