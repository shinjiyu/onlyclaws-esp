# 6. On-device inference: models as signed data, fixed op set

## Status

Accepted

## Context

Agents already change device behaviour without reflashing by deploying Lua. They could not deploy perception: a keyword spotter or a bird-call detector had to be compiled into the firmware. The S3 boards have 8 MB PSRAM and a 3.4 MB `spiffs` data partition that nothing used, which is enough for several small models.

Espressif's ESP-DL v3 needs ESP-IDF 5.3; the firmware is on Arduino-ESP32 2.0.17 (IDF 4.4). TensorFlow Lite Micro builds on IDF 4.4, and esp-nn gives it S3 SIMD kernels for the int8 ops that dominate small CNNs.

A `.tflite` file is a flatbuffer interpreted by C++ that was never hardened against hostile input, and the device channel uses `setInsecure()` TLS. Whatever the device runs must be checked before the interpreter sees it.

## Decision

- **New plugin `ml`** (`OC_PLUGIN_ML`, S3 envs only): TFLite Micro 1.4.1 + esp-nn, vendored by `scripts/fetch_tflm.sh` at pinned commits into `rlcd/lib/` (git-ignored).
- **Fixed operator set.** Firmware registers op set v1 (34 builtins + 11 TFLM Signal ops for audio frontends). The control plane parses every upload and refuses ops outside the set, so a model either runs on every device with that op set or is rejected at upload with the op names. New ops mean a new op set number and a firmware release; op sets are append-only.
- **Models are data.** Manifest JSON (`name, version, opset, kind, sha256, bytes, arena_kb, labels, audio{…}`) plus the blob. Format and limits in [`ML-PLUGIN.md`](../ML-PLUGIN.md).
- **Signed delivery.** The control plane signs the exact manifest bytes with ECDSA P-256. Firmware carries the public key (`OC_ML_PUBKEY_PEM`), verifies the signature, parses the manifest, then checks the blob's sha256. A build without a key refuses all models.
- **Cache.** Verified envelope + blob live on LittleFS (`spiffs` partition, `/ml/<name>.{json,tfl}`), so models keep working offline; the cached envelope is re-verified on every load.
- **Audio pipeline in firmware, DSP in the model.** `kind: audio` models name a `kind: frontend` model (e.g. the TFLM Signal mel frontend). Firmware only frames 16 kHz mic samples, runs the frontend per window, stacks rows and runs the classifier. The mic reaches `ml` as a hook from `device_runtime` (audio plugin wrapper), so there is no `ml → audio` edge.
- **Lua API** `ml.load/listen/run/unload/info`; `/status` reports `meta.ml = {opset, models}`; capability `ml`.
- **Server** `ml_registry` router (agent upload/list/delete, device envelope/blob), per-owner storage under `data/ml/`, devices only see their owner's models.

## Consequences

- Reqs `REQ-ML-OPSET`, `REQ-ML-SIGNED-DELIVERY`, `REQ-ML-MANIFEST`, `REQ-ML-RUN`, `REQ-ML-KWS`; graph nodes `ml` (plugin) and `ml_registry` (infra).
- ML envs compile as C++17 (`build_unflags = -std=gnu++11`). TFLM is built with `-fno-exceptions` (its classes hide `operator delete`) and at the default `-Os`: GCC 12.2 for Xtensa crashes on TFLM's float reference kernels at `-O2`/`-O3`. esp-nn keeps `-O2`.
- The RLCD image with ML is 1.65 MB of the 6.4 MB app partition; models and arenas live in PSRAM.
- Model blobs are trusted only as far as the signing key: keep it on the server (`EPD_ML_SIGNING_KEY`, default `data/ml_signing_key.pem`), never in git. Rotating it needs a firmware release.
- Models outside the op set (e.g. BirdNET's full network) need either a smaller student model or a new op set.
