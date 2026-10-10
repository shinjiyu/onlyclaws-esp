# ML plugin: model format and op set

Decision record: [ADR 0006](./decisions/0006-ml-models-as-data.md).

## Flow

1. Agent uploads a `.tflite` + meta to `POST /api/ml/models`.
2. Control plane parses the flatbuffer, rejects ops outside the op set, builds the manifest, signs it.
3. Lua on the device calls `ml.load(name)` (or `ml.listen` / `ml.run`, which load on first use).
4. Device fetches `GET /api/v1/device/{id}/models/{name}` → `{"manifest": "<json>", "sig": "<base64 DER>"}`, verifies the ECDSA P-256 signature over the exact manifest bytes, parses the manifest, then fetches `/blob` and checks `sha256` and `bytes`.
5. Envelope and blob are cached on LittleFS (`/ml/<name>.json`, `/ml/<name>.tfl`). Offline loads use the cache and verify it again.

## Manifest

```json
{
  "name": "micro_speech", "version": 2, "opset": 1, "kind": "audio",
  "sha256": "<64 lowercase hex>", "bytes": 18800, "arena_kb": 40,
  "labels": ["silence", "unknown", "yes", "no"],
  "audio": {"rate": 16000, "window_ms": 30, "stride_ms": 20, "frames": 49,
            "features": 40, "frontend": "ms_frontend"}
}
```

| Field | Rule |
|-------|------|
| `name` | `[a-z0-9_-]{1,32}` |
| `version` | Set by the server, +1 per upload of the same name |
| `opset` | 1..firmware op set; newer → device refuses ("update firmware") |
| `kind` | `audio` (mic classifier), `frontend` (per-window feature model used by audio models), `tensor` (anything fed via `ml.run`) |
| `bytes` | ≤ 2 MB |
| `arena_kb` | 1..1024; TFLM tensor arena in PSRAM. Too small → `AllocateTensors failed` |
| `labels` | ≤ 64 strings ≤ 32 chars; index = output index |
| `audio.rate` | 16000 only (the mic rate) |
| `audio.*_ms`, `frames`, `features` | Clip = `(frames-1)·stride + window` samples ≤ 10 s |
| `audio.frontend` | Another model of kind `frontend`, uploaded first |

Agent meta for upload is the same object without `version`, `opset`, `sha256`, `bytes`.

## Audio pipeline

`ml.listen(name)` drains ~60 ms of stale mic data, records one clip, then for each of `frames` windows (`window_ms` long, every `stride_ms`) copies the int16 samples into the frontend's input, invokes it and copies its output row into the classifier input. The frontend's output must have `features` elements and the same type as the classifier input (`frames × features` elements). The classifier output is dequantized to floats.

Frontends keep state across windows (noise estimate, PCAN), as in the TFLM `micro_speech` example.

## Op set v1

Builtins: Add, AveragePool2D, Cast, Concatenation, Conv2D, DepthwiseConv2D, Dequantize, Div, ExpandDims, FullyConnected, HardSwish, LeakyRelu, Logistic, MaxPool2D, Maximum, Mean, Minimum, Mul, Pack, Pad, Quantize, Relu, Relu6, Reshape, Shape, Slice, Softmax, Split, Squeeze, StridedSlice, Sub, Tanh, Transpose, Unpack.

Custom (TFLM Signal): SignalWindow, SignalFftAutoScale, SignalRfft, SignalEnergy, SignalFilterBank, SignalFilterBankSquareRoot, SignalFilterBankSpectralSubtraction, SignalPCAN, SignalFilterBankLog, SignalFramer, SignalStacker.

Source of truth: `registerOpsetV1()` in `rlcd/src/ml_engine.cpp`; `server/ml_opset.py` mirrors it and `server/tests/test_ml_registry.py` fails if they differ. `GET /api/ml/opset` returns the list.

## Lua

| Call | Returns |
|------|---------|
| `ml.load(name)` | `true` or `nil, err` |
| `ml.listen(name)` | `{label, index, score, scores, ms}` or `nil, err` (blocks for one clip + inference) |
| `ml.run(name, {numbers})` | same result table; input quantized to the tensor type |
| `ml.info(name)` | `{name, version, kind, labels, arena_used, inputs, outputs}` or `nil` if not loaded |
| `ml.unload(name)` | — |

Up to 6 models stay loaded; the least recently used is evicted (an audio model's frontend is kept while it loads).

## Keys

- Private key: server only, `EPD_ML_SIGNING_KEY` (default `<data>/ml_signing_key.pem`), mode 600. Without it uploads return 503.
- Public key: `OC_ML_PUBKEY_PEM` in `rlcd/include/cloud_config.h`. Empty → device refuses every model unless built with `-DOC_ML_ALLOW_UNSIGNED` (bench only).
