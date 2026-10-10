#pragma once

#include <Arduino.h>

// Authenticated device channel (pending / status / ack / assets).
// Lua http.* uses a separate TLS session and does not go through here.

bool cloudHttpJson(const char *method, const String &url, const String &body, String &out,
                   uint32_t timeoutMs);

// Read exactly `need` bytes into dst. False on transport or short body.
bool cloudHttpGetExact(const String &url, uint8_t *dst, size_t need, uint32_t timeoutMs);

// GET a named bitmap. On success, *data is malloc'd and owned by the caller.
// Width/height come from X-Width / X-Height. Caps at 800x480, width multiple of 8.
bool cloudHttpGetBitmap(const String &url, int *w, int *h, uint8_t **data, size_t *n);

// GET a body of known Content-Length (<= maxBytes) into PSRAM, 16-byte
// aligned (TFLite Micro model buffers). On success the caller owns *data (free()).
bool cloudHttpGetBlob(const String &url, size_t maxBytes, uint8_t **data, size_t *n,
                      uint32_t timeoutMs);
