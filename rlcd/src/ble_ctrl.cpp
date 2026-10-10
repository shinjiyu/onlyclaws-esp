#include "ble_ctrl.h"

#include <NimBLEDevice.h>
#include <esp_mac.h>
#include <esp_system.h>
#include <string.h>

#include "pad_ctrl.h"

namespace {

constexpr const char *kSvcUuid = "a1b20001-c3d4-4e5f-8091-23456789abcd";
constexpr const char *kDirUuid = "a1b20002-c3d4-4e5f-8091-23456789abcd";
constexpr const char *kRstUuid = "a1b20003-c3d4-4e5f-8091-23456789abcd";

constexpr const char *kNusUuid = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
constexpr const char *kNusRxUuid = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";
constexpr const char *kNusTxUuid = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";

NimBLEServer *gServer = nullptr;
NimBLECharacteristic *gTx = nullptr;
bool gStarted = false;
volatile bool gBleConnected = false;
char gName[24] = {0};

BleUartRxFn gUartRx = nullptr;
BlePairingFn gPairing = nullptr;
volatile uint16_t gUartConn = BLE_HS_CONN_HANDLE_NONE;
volatile bool gUartSecure = false;

bool linkSecure(const ble_gap_conn_desc *desc) {
  return desc && desc->sec_state.encrypted && desc->sec_state.authenticated;
}

void requestSecurity(const ble_gap_conn_desc *desc) {
  if (!desc || desc->sec_state.encrypted) return;
  NimBLEDevice::startSecurity(desc->conn_handle);
}

char parseDirByte(uint8_t b) {
  if (b == 'U' || b == 'u' || b == 1) return 'U';
  if (b == 'D' || b == 'd' || b == 2) return 'D';
  if (b == 'L' || b == 'l' || b == 3) return 'L';
  if (b == 'R' || b == 'r' || b == 4) return 'R';
  return 0;
}

class ServerCbs : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer *pServer, ble_gap_conn_desc *desc) override {
    gBleConnected = true;
    padCtrlSetLink(true);
    Serial.printf("[ble] connected handle=%u peers=%u\n", desc->conn_handle,
                  (unsigned)pServer->getConnectedCount());
    // Keep advertising so a phone pad and Claude desktop can both connect.
    if (pServer->getConnectedCount() < CONFIG_BT_NIMBLE_MAX_CONNECTIONS) {
      NimBLEDevice::startAdvertising();
    }
  }
  void onDisconnect(NimBLEServer *pServer, ble_gap_conn_desc *desc) override {
    gBleConnected = pServer->getConnectedCount() > 0;
    if (desc->conn_handle == gUartConn) {
      gUartConn = BLE_HS_CONN_HANDLE_NONE;
      gUartSecure = false;
    }
    if (gPairing) gPairing(0);
    Serial.println("[ble] disconnected — advertising");
    NimBLEDevice::startAdvertising();
  }
  uint32_t onPassKeyRequest() override {
    const uint32_t pk = 100000 + esp_random() % 900000;
    if (gPairing) gPairing(pk);
    Serial.println("[ble] pairing: passkey on panel");
    return pk;
  }
  void onAuthenticationComplete(ble_gap_conn_desc *desc) override {
    Serial.printf("[ble] auth handle=%u enc=%d authn=%d bonded=%d\n", desc->conn_handle,
                  desc->sec_state.encrypted, desc->sec_state.authenticated,
                  desc->sec_state.bonded);
    if (desc->conn_handle == gUartConn) gUartSecure = linkSecure(desc);
    if (gPairing) gPairing(0);
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

class UartRxCbs : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c, ble_gap_conn_desc *desc) override {
    gUartConn = desc->conn_handle;
    gUartSecure = linkSecure(desc);
    if (!gUartSecure) {
      requestSecurity(desc);
      return;
    }
    std::string v = c->getValue();
    if (gUartRx && !v.empty()) gUartRx((const uint8_t *)v.data(), v.size());
  }
};

class UartTxCbs : public NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic *c, ble_gap_conn_desc *desc, uint16_t subValue) override {
    (void)c;
    if (!subValue) return;
    gUartConn = desc->conn_handle;
    gUartSecure = linkSecure(desc);
    requestSecurity(desc);
  }
};

ServerCbs gServerCbs;
DirCbs gDirCbs;
RstCbs gRstCbs;
UartRxCbs gUartRxCbs;
UartTxCbs gUartTxCbs;

}  // namespace

void bleCtrlBegin(const char *advName) {
  if (gStarted) return;
  if (advName && advName[0]) {
    strncpy(gName, advName, sizeof(gName) - 1);
  } else {
    uint8_t mac[6] = {};
    esp_read_mac(mac, ESP_MAC_BT);
    // The Claude desktop device picker filters on the "Claude" prefix.
    snprintf(gName, sizeof(gName), "Claude-OC-%02X%02X", mac[4], mac[5]);
  }

  NimBLEDevice::init(gName);
  NimBLEDevice::setPower(ESP_PWR_LVL_P6);
  NimBLEDevice::setMTU(247);
  NimBLEDevice::setSecurityAuth(true, true, true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);

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

  NimBLEService *nus = gServer->createService(kNusUuid);
  auto *rx = nus->createCharacteristic(kNusRxUuid,
                                       NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  rx->setCallbacks(&gUartRxCbs);
  gTx = nus->createCharacteristic(kNusTxUuid, NIMBLE_PROPERTY::NOTIFY);
  gTx->setCallbacks(&gUartTxCbs);
  nus->start();

  // Only one 128-bit UUID fits next to the flags; the name moves to the
  // scan response.
  NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(kNusUuid);
  adv->setName(gName);
  adv->setScanResponse(true);
  adv->start();

  gStarted = true;
  Serial.printf("[ble] advertising as %s\n", gName);
}

bool bleCtrlConnected() { return gBleConnected; }

const char *bleCtrlName() { return gName; }

char bleCtrlDir() { return padCtrlDir(); }

bool bleCtrlTakeRestart() { return padCtrlTakeRestart(); }

void bleCtrlSetUartRx(BleUartRxFn fn) { gUartRx = fn; }

void bleCtrlSetPairing(BlePairingFn fn) { gPairing = fn; }

bool bleCtrlUartSend(const char *data, size_t n) {
  const uint16_t conn = gUartConn;
  if (!gStarted || !gTx || !data || conn == BLE_HS_CONN_HANDLE_NONE || !gUartSecure) {
    return false;
  }
  const uint16_t mtu = gServer->getPeerMTU(conn);
  size_t chunk = mtu > 3 ? (size_t)mtu - 3 : 20;
  if (chunk > 244) chunk = 244;
  for (size_t off = 0; off < n; off += chunk) {
    const size_t len = (n - off) < chunk ? (n - off) : chunk;
    gTx->notify((const uint8_t *)data + off, len);
  }
  return true;
}

bool bleCtrlUartSecure() { return gUartSecure; }

void bleCtrlForgetBonds() {
  NimBLEDevice::deleteAllBonds();
  Serial.println("[ble] bonds erased");
}
