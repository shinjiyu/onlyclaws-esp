# Web-flash firmware packages

Bins for `/flash` (ESP Web Tools). **Do not commit `*.bin`.**

**Public SKU (CI):** only `esp32-s3-amoled-175c` is listed on `/api/firmware` and built by
`.github/workflows/web-flash-amoled.yml`. Other envs can still be packaged locally; pass `?all=1`
to the API when debugging.

Layout per product id (see `firmware_catalog.py`):

```
server/firmware/<product-id>/
  VERSION
  manifest.json          # written by package script
  bootloader.bin
  partitions.bin
  boot_app0.bin
  firmware.bin
  # or: merged.bin at offset 0
```

Build then package from the repo root:

```bash
cd rlcd && pio run -e esp32-s3-amoled-175c
bash scripts/package_web_flash.sh          # defaults to amoled-175c
```

Deploy artifact from CI onto the host (example):

```bash
# download the workflow artifact, then:
rsync -a web-flash-esp32-s3-amoled-175c-*/ /var/lib/onlyclaws/firmware/esp32-s3-amoled-175c/
# with OC_FIRMWARE_DIR=/var/lib/onlyclaws/firmware on the service
```
