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
