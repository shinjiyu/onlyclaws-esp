#include "pad_ctrl.h"

namespace {
volatile char gDir = 'R';
volatile bool gRestart = false;
volatile bool gLinked = false;
}  // namespace

void padCtrlSetDir(char d) {
  if (d == 'U' || d == 'D' || d == 'L' || d == 'R') gDir = d;
}

char padCtrlDir() { return gDir; }

void padCtrlRequestRestart() { gRestart = true; }

bool padCtrlTakeRestart() {
  if (!gRestart) return false;
  gRestart = false;
  return true;
}

void padCtrlSetLink(bool on) { gLinked = on; }

bool padCtrlLinked() { return gLinked; }
