# 7. Lua scripts persist on a LittleFS partition

## Status

Accepted

## Context

Deployed Lua lived in RAM. A reboot cleared it, so a board with no network could not resume the last script, and the cloud had to send the same source again after every power loss.

The S3 boards already mount LittleFS on the `spiffs` label for ML models, through the Arduino `LittleFS` singleton, which can only hold one partition. Script files need their own partition so an app OTA does not erase them and so they do not share that singleton.

The device channel is the same one that required signed ML manifests: a script must be checked before it is written to flash.

## Decision

- Add a 128 KB data partition labeled `littlefs` beside the OTA app slots. On 16 MB boards, shrink `app1` only; leave the `spiffs` ML cache at its old offset and size. On the 4 MB RoArm board, keep the 3 MB app slot and carve `littlefs` from the unused spiffs region.
- Mount it with `esp_vfs_littlefs_register` (not the Arduino `LittleFS` object). Refuse to mount if the partition overlaps an app slot. Do not erase it from the upload or OTA path.
- The control plane signs each deploy with Ed25519. The device verifies the signature and the content hash before accepting the file. Writes use a `.tmp` file, a read-back, and `rename`. The index is a separate file with the same replace sequence.
- Keep the last 3 versions of the one active script. Boot loads the newest valid one. A failed load marks that version bad and tries the previous. If none run, stay in safe mode and wait for a new deploy.
- `POST /api/script/stop` clears the run flag. The files stay until a later deploy replaces them.

## Consequences

- Requirement `REQ-SCRIPT-PERSIST`. Format, partition math, and key setup: [`SCRIPT-PERSIST.md`](../SCRIPT-PERSIST.md).
- `EPD_SCRIPT_SIGNING_KEY` must exist or deploy returns 503. The matching public key is `OC_SCRIPT_PUBKEY_HEX`. Rotating it takes a firmware build.
- A one-time flash of the new partition table is required. Later app uploads leave `littlefs` in place.
- Firmware that still ignores unknown JSON fields keeps running the unsigned `source` from RAM. This firmware does not.
