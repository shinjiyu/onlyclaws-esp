#include "arm_usb_serial.h"

#if OC_CAP_ARM

#include <ArduinoJson.h>

#include "arm_ctl.h"
#include "arm_driver.h"
#include "capability.h"

namespace {

String lineBuf;

void replyOk() { Serial.println("{\"ok\":true}"); }

void replyErr(const char *msg) {
  Serial.print("{\"ok\":false,\"err\":\"");
  Serial.print(msg);
  Serial.println("\"}");
}

void handleLine(const String &line) {
  if (line.length() < 2 || line[0] != '{') return;

  DynamicJsonDocument doc(384);
  DeserializationError err = deserializeJson(doc, line);
  if (err) return;

  const char *tool = doc["tool"] | "";
  if (!tool[0]) return;

  ArmDriver *arm = armDriver();
  if (!arm) {
    replyErr("no_arm");
    return;
  }

  if (!strcmp(tool, "arm.feedback")) {
    ArmPose p{};
    if (!arm->feedback(p)) {
      replyErr("feedback_fail");
      return;
    }
    char buf[160];
    snprintf(buf, sizeof(buf),
             "{\"ok\":true,\"q\":[%.5f,%.5f,%.5f,%.5f]}", p.q[0], p.q[1], p.q[2],
             p.q[3]);
    Serial.println(buf);
    return;
  }

  if (!strcmp(tool, "arm.stop")) {
    armCtlHostPreempt();
    if (!arm->stop()) {
      replyErr("stop_fail");
      return;
    }
    replyOk();
    return;
  }

  if (!strcmp(tool, "arm.stream") || !strcmp(tool, "arm.move")) {
    armCtlHostPreempt();
    ArmPose p{};
    if (doc["q"].is<JsonArray>()) {
      JsonArray q = doc["q"].as<JsonArray>();
      for (int i = 0; i < 4; ++i) p.q[i] = q[i] | 0.f;
    } else {
      p.q[0] = doc["base"] | 0.f;
      p.q[1] = doc["shoulder"] | 0.f;
      p.q[2] = doc["elbow"] | 1.57f;
      p.q[3] = doc["hand"] | doc["wrist"] | 3.14f;
    }
    int spd = doc["spd"] | 0;
    if (!arm->stream(p, spd)) {
      replyErr("stream_fail");
      return;
    }
    replyOk();
    return;
  }
}

}  // namespace

void armUsbSerialPoll() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (lineBuf.length()) {
        handleLine(lineBuf);
        lineBuf = "";
      }
      continue;
    }
    if (lineBuf.length() < 300) lineBuf += c;
    else
      lineBuf = "";
  }
}

#endif  // OC_CAP_ARM
