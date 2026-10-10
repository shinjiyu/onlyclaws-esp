#pragma once

// Private OnlyClaws control plane (defaults).
// Runtime override: NVS namespace "cloud" keys host / path_prefix / device_id.
// Secrets (token) stay in device_secrets.h (gitignored).

#ifndef CLOUD_API_SCHEME
#define CLOUD_API_SCHEME "https"
#endif

#ifndef CLOUD_API_HOST
#define CLOUD_API_HOST "onlyclaws.world"
#endif

// Public path prefix for the app (no trailing slash).
#ifndef CLOUD_API_PATH_PREFIX
#define CLOUD_API_PATH_PREFIX "/epaper"
#endif

#ifndef CLOUD_PUBLIC_BASE
#define CLOUD_PUBLIC_BASE CLOUD_API_SCHEME "://" CLOUD_API_HOST CLOUD_API_PATH_PREFIX
#endif

// ECDSA P-256 key the control plane signs ml model manifests with
// (EPD_ML_SIGNING_KEY on the server). Self-hosters replace it with their own
// public key; an empty string refuses every model unless
// OC_ML_ALLOW_UNSIGNED is defined.
#ifndef OC_ML_PUBKEY_PEM
#define OC_ML_PUBKEY_PEM                                                   \
  "-----BEGIN PUBLIC KEY-----\n"                                           \
  "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEczxHt/Y+Z+Hk0j4wh8e5z7Lc+L2W\n"    \
  "zwBo9CwFwXM6svCoaZ03CPsWG72UexDFb9GkWgdz5cR5A7w8FYTHqPPy3Q==\n"        \
  "-----END PUBLIC KEY-----\n"
#endif
