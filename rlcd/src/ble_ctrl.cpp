#include "ble_ctrl.h"

#include <NimBLEDevice.h>
#include <string.h>

#include "pad_ctrl.h"

namespace {

constexpr const char *kSvcUuid = "a1b20001-c3d4-4e5f-8091-23456789abcd";
constexpr const char *kDirUuid = "a1b20002-c3d4-4e5f-8091-23456789abcd";
constexpr const char *kRstUuid = "a1b20003-c3d4-4e5f-8091-23456789abcd";

NimBLEServer *gServer = nullptr;
bool gStarted = false;
volatile bool gBleConnected = false;

char parseDirByte(uint8_t b) {
  if (b == 'U' || b == 'u' || b == 1) return 'U';
  if (b == 'D' || b == 'd' || b == 2) return 'D';
  if (b == 'L' || b == 'l' || b == 3) return 'L';
  if (b == 'R' || b == 'r' || b == 4) return 'R';
  return 0;
}

class ServerCbs : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer *pServer) override {
    (void)pServer;
    gBleConnected = true;
    padCtrlSetLink(true);
    Serial.println("[ble] connected");
  }
  void onDisconnect(NimBLEServer *pServer) override {
    (void)pServer;
    gBleConnected = false;
    Serial.println("[ble] disconnected — advertising");
    NimBLEDevice::startAdvertising();
  }
};

class DirCbs : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c) override {
    std::string v = c->getValue();
    if (v.empty()) return;
    char d = parseDirByte((uint8_t)v[0]);
    if (d) {
      padCtrlSetDir(d);
      Serial.printf("[ble] dir=%c\n", d);
    }
  }
};

class RstCbs : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c) override {
    (void)c;
    padCtrlRequestRestart();
    Serial.println("[ble] restart");
  }
};

ServerCbs gServerCbs;
DirCbs gDirCbs;
RstCbs gRstCbs;

}  // namespace

void bleCtrlBegin(const char *advName) {
  if (gStarted) return;
  const char *name = (advName && advName[0]) ? advName : "OC-Snake";

  NimBLEDevice::init(name);
  NimBLEDevice::setPower(ESP_PWR_LVL_P6);
  NimBLEDevice::setSecurityAuth(false, false, false);

  gServer = NimBLEDevice::createServer();
  gServer->setCallbacks(&gServerCbs);

  NimBLEService *svc = gServer->createService(kSvcUuid);
  auto *dirChar = svc->createCharacteristic(
      kDirUuid, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  dirChar->setCallbacks(&gDirCbs);
  auto *rstChar = svc->createCharacteristic(
      kRstUuid, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  rstChar->setCallbacks(&gRstCbs);
  svc->start();

  NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(kSvcUuid);
  adv->setName(name);
  adv->setScanResponse(true);
  adv->start();

  gStarted = true;
  Serial.printf("[ble] advertising as %s\n", name);
}

bool bleCtrlConnected() { return gBleConnected; }

char bleCtrlDir() { return padCtrlDir(); }

bool bleCtrlTakeRestart() { return padCtrlTakeRestart(); }
