#include "capability.h"

#include <string.h>

void capabilityFillJson(JsonArray out) {
  out.add("core");
  if (ocCapPanel()) out.add("panel");
  if (ocCapAudio()) out.add("audio");
  if (ocCapBle()) out.add("ble_pad");
  if (ocCapSensors()) out.add("sensors");
  if (ocCapArm()) out.add("arm");
}

bool capabilityAllowsTool(const char *tool) {
  if (!tool || !tool[0]) return false;

  // Always-safe bookkeeping
  if (!strcmp(tool, "emit")) return true;

  if (!strcmp(tool, "sensors.read") || !strcmp(tool, "sensors")) {
    return ocCapSensors();
  }
  if (!strcmp(tool, "beep") || !strcmp(tool, "play_pcm")) {
    return ocCapAudio();
  }
  if (!strcmp(tool, "display") || !strcmp(tool, "gfx.flush") ||
      !strcmp(tool, "gfx.clear")) {
    return ocCapPanel();
  }
  if (!strncmp(tool, "arm.", 4) || !strcmp(tool, "arm")) {
    return ocCapArm();
  }
  return false;
}
