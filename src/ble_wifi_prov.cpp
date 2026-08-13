#include "ble_wifi_prov.h"

#include <ArduinoJson.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <WiFi.h>

#include "device_secrets.h"
#include "wifi_store.h"

// Custom GATT service for WiFi provisioning.
static constexpr const char *SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
static constexpr const char *RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";  // phone -> esp
static constexpr const char *TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";  // esp -> phone

namespace {
BLEServer *server = nullptr;
BLECharacteristic *txChar = nullptr;
volatile bool gotCreds = false;
volatile bool connected = false;
String pendingSsid;
String pendingPass;

void notifyStatus(const String &msg) {
  Serial.printf("[ble-prov] %s\n", msg.c_str());
  if (!txChar) return;
  txChar->setValue(msg.c_str());
  txChar->notify();
}

class ServerCbs : public BLEServerCallbacks {
  void onConnect(BLEServer *) override { connected = true; }
  void onDisconnect(BLEServer *s) override {
    connected = false;
    if (!gotCreds) s->startAdvertising();
  }
};

class RxCbs : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    std::string v = c->getValue();
    if (v.empty()) return;
    String raw(v.c_str());
    Serial.printf("[ble-prov] rx %u bytes\n", (unsigned)raw.length());

    DynamicJsonDocument doc(768);
    if (deserializeJson(doc, raw)) {
      notifyStatus("{\"ok\":false,\"msg\":\"bad json\"}");
      return;
    }

    const char *cmd = doc["cmd"] | "";
    if (strcmp(cmd, "clear") == 0) {
      wifiStoreClear();
      notifyStatus("{\"ok\":true,\"msg\":\"cleared\"}");
      return;
    }
    if (strcmp(cmd, "info") == 0) {
      String info = String("{\"ok\":true,\"device\":\"") + EPD_DEVICE_ID +
                    "\",\"mac\":\"" + WiFi.macAddress() + "\"}";
      notifyStatus(info);
      return;
    }

    const char *ssid = doc["ssid"] | "";
    const char *pass = doc["pass"] | doc["password"] | "";
    if (!ssid[0]) {
      notifyStatus("{\"ok\":false,\"msg\":\"ssid required\"}");
      return;
    }

    pendingSsid = ssid;
    pendingPass = pass;
    if (!wifiStoreSave(pendingSsid, pendingPass)) {
      notifyStatus("{\"ok\":false,\"msg\":\"nvs save failed\"}");
      return;
    }
    gotCreds = true;
    notifyStatus("{\"ok\":true,\"msg\":\"saved\",\"ssid\":\"" + pendingSsid + "\"}");
  }
};
}  // namespace

bool bleWifiProvGotCreds() { return gotCreds; }

void bleWifiProvStop() {
  BLEDevice::deinit(true);
  server = nullptr;
  txChar = nullptr;
}

bool bleWifiProvision(uint32_t timeoutMs) {
  gotCreds = false;
  pendingSsid = "";
  pendingPass = "";

  String name = String("EPD-") + EPD_DEVICE_ID;
  Serial.printf("[ble-prov] start as %s\n", name.c_str());
  Serial.println(
      "[ble-prov] Write JSON to RX char:\n"
      "  {\"ssid\":\"YourWifi\",\"pass\":\"secret\"}\n"
      "  {\"cmd\":\"info\"} / {\"cmd\":\"clear\"}");

  BLEDevice::init(name.c_str());
  server = BLEDevice::createServer();
  server->setCallbacks(new ServerCbs());

  BLEService *svc = server->createService(SVC_UUID);
  BLECharacteristic *rx = svc->createCharacteristic(
      RX_UUID, BLECharacteristic::PROPERTY_WRITE |
                   BLECharacteristic::PROPERTY_WRITE_NR);
  rx->setCallbacks(new RxCbs());

  txChar = svc->createCharacteristic(
      TX_UUID, BLECharacteristic::PROPERTY_READ |
                   BLECharacteristic::PROPERTY_NOTIFY);
  txChar->addDescriptor(new BLE2902());
  txChar->setValue("{\"ok\":true,\"msg\":\"ready\"}");

  svc->start();
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SVC_UUID);
  adv->setScanResponse(true);
  adv->setMinPreferred(0x06);
  adv->setMinPreferred(0x12);
  BLEDevice::startAdvertising();

  const uint32_t start = millis();
  while (!gotCreds) {
    if (timeoutMs && millis() - start > timeoutMs) {
      Serial.println("[ble-prov] timeout");
      bleWifiProvStop();
      return false;
    }
    delay(50);
  }

  delay(300);  // let notify flush
  bleWifiProvStop();
  return true;
}
