#include "sts_bus.h"

#include <string.h>

namespace sts {
namespace {

HardwareSerial *gSer = nullptr;
int gLastErr = 0;

void host2scs(uint8_t *l, uint8_t *h, int16_t v) {
  *l = (uint8_t)(v & 0xFF);
  *h = (uint8_t)((v >> 8) & 0xFF);
}

int16_t scs2host(uint8_t l, uint8_t h) {
  return (int16_t)((h << 8) | l);
}

uint8_t checksum(const uint8_t *buf, size_t n) {
  uint8_t s = 0;
  for (size_t i = 2; i < n; ++i) s += buf[i];
  return ~s;
}

void flushInput() {
  if (!gSer) return;
  while (gSer->available() > 0) (void)gSer->read();
}

bool writePacket(const uint8_t *pkt, size_t n) {
  if (!gSer || !pkt || !n) return false;
  flushInput();
  size_t wrote = gSer->write(pkt, n);
  gSer->flush();
  // Half-duplex: echo of our TX is already in RX FIFO. Drop at most n bytes that
  // are present *now* — do not wait (waiting eats the real reply).
  delayMicroseconds(20);
  size_t drop = 0;
  while (drop < n && gSer->available() > 0) {
    (void)gSer->read();
    ++drop;
  }
  return wrote == n;
}

bool readByte(uint8_t &out, uint32_t timeoutMs) {
  const uint32_t t0 = millis();
  while ((millis() - t0) <= timeoutMs) {
    if (gSer->available() > 0) {
      out = (uint8_t)gSer->read();
      return true;
    }
    delayMicroseconds(20);
  }
  return false;
}

bool checkHead(uint32_t timeoutMs) {
  uint8_t b = 0;
  uint8_t prev = 0;
  bool havePrev = false;
  uint8_t junk = 0;
  const uint32_t t0 = millis();
  while ((millis() - t0) <= timeoutMs) {
    if (!readByte(b, 5)) {
      if (junk > 40) return false;
      continue;
    }
    if (havePrev && prev == 0xFF && b == 0xFF) return true;
    prev = b;
    havePrev = true;
    ++junk;
    if (junk > 64) return false;
  }
  return false;
}

// Status: FF FF ID Length Error [params…] CS  (Length includes Error..CS)
bool readStatus(uint8_t expectId, uint8_t *data, uint8_t dataLen, uint32_t timeoutMs) {
  if (!checkHead(timeoutMs)) {
    gLastErr = 2;
    return false;
  }
  uint8_t id = 0, len = 0, err = 0;
  if (!readByte(id, timeoutMs) || !readByte(len, timeoutMs) || !readByte(err, timeoutMs)) {
    gLastErr = 3;
    return false;
  }
  if (id != expectId) {
    gLastErr = 4;
    return false;
  }
  // Remaining after Error: (len - 2) bytes of params + 1 checksum = len - 1
  if (len < 2 || len > 16) {
    gLastErr = 5;
    return false;
  }
  const uint8_t paramBytes = (uint8_t)(len - 2);  // exclude Error and CS
  if (dataLen > paramBytes) {
    gLastErr = 7;
    return false;
  }
  uint8_t params[16];
  for (uint8_t i = 0; i < paramBytes; ++i) {
    if (!readByte(params[i], timeoutMs)) {
      gLastErr = 6;
      return false;
    }
  }
  uint8_t cs = 0;
  if (!readByte(cs, timeoutMs)) {
    gLastErr = 8;
    return false;
  }
  uint8_t sum = id + len + err;
  for (uint8_t i = 0; i < paramBytes; ++i) sum += params[i];
  if ((uint8_t)(~sum) != cs) {
    gLastErr = 9;
    return false;
  }
  if (data && dataLen) memcpy(data, params, dataLen);
  gLastErr = 0;
  return true;
}

bool genWrite(uint8_t id, uint8_t addr, const uint8_t *data, uint8_t dataLen) {
  uint8_t buf[24];
  if (dataLen + 7 > sizeof(buf)) return false;
  buf[0] = 0xFF;
  buf[1] = 0xFF;
  buf[2] = id;
  buf[3] = (uint8_t)(dataLen + 3);
  buf[4] = INST_WRITE;
  buf[5] = addr;
  if (dataLen) memcpy(buf + 6, data, dataLen);
  const size_t beforeCs = 6 + dataLen;
  buf[beforeCs] = checksum(buf, beforeCs);
  if (!writePacket(buf, beforeCs + 1)) return false;
  // Level=1: servos ACK writes. Consume ACK so it won't poison the next read.
  return readStatus(id, nullptr, 0, 40);
}

bool genRead(uint8_t id, uint8_t addr, uint8_t nBytes, uint8_t *out) {
  // Official: writeBuf(ID, MemAddr, &nLen, 1, INST_READ) → Length=4
  uint8_t req[8] = {0xFF, 0xFF, id, 0x04, INST_READ, addr, nBytes, 0};
  req[7] = checksum(req, 7);
  if (!writePacket(req, 8)) {
    gLastErr = 1;
    return false;
  }
  return readStatus(id, out, nBytes, 100);
}

}  // namespace

bool begin(HardwareSerial &serial, int rxPin, int txPin, uint32_t baud) {
  gSer = &serial;
  gSer->begin(baud, SERIAL_8N1, rxPin, txPin);
  delay(80);
  flushInput();
  return true;
}

void end() {
  if (gSer) gSer->end();
  gSer = nullptr;
}

int lastError() { return gLastErr; }

bool writePosEx(uint8_t id, int16_t position, uint16_t speed, uint8_t acc) {
  int16_t pos = position;
  if (pos < 0) {
    pos = (int16_t)(-pos);
    pos = (int16_t)(pos | (1 << 15));
  }
  uint8_t b[7];
  b[0] = acc;
  host2scs(b + 1, b + 2, pos);
  host2scs(b + 3, b + 4, 0);
  host2scs(b + 5, b + 6, (int16_t)speed);
  return genWrite(id, ADDR_ACC, b, 7);
}

bool readPos(uint8_t id, int16_t &positionOut) {
  uint8_t raw[2] = {};
  if (!genRead(id, ADDR_PRESENT_POSITION_L, 2, raw)) return false;
  int16_t v = scs2host(raw[0], raw[1]);
  if (v & (1 << 15)) {
    v = (int16_t)(-(v & ~(1 << 15)));
  }
  positionOut = v;
  return true;
}

bool enableTorque(uint8_t id, bool on) {
  uint8_t v = on ? 1 : 0;
  return genWrite(id, 40, &v, 1);
}

bool ping(uint8_t id) {
  uint8_t req[6] = {0xFF, 0xFF, id, 0x02, 0x01, 0};
  req[5] = checksum(req, 5);
  if (!writePacket(req, 6)) return false;
  return readStatus(id, nullptr, 0, 100);
}

}  // namespace sts
