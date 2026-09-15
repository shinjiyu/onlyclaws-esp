#include "wifi_ap_prov.h"

#include <DNSServer.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_mac.h>

#include "wifi_store.h"

namespace {
DNSServer dns;
WebServer server(80);
volatile bool done = false;
String statusMsg;
String apSsid;
String deviceId;

String htmlEscape(const String &s) {
  String o;
  o.reserve(s.length() + 8);
  for (size_t i = 0; i < s.length(); ++i) {
    char c = s[i];
    if (c == '&')
      o += "&amp;";
    else if (c == '<')
      o += "&lt;";
    else if (c == '>')
      o += "&gt;";
    else if (c == '"')
      o += "&quot;";
    else
      o += c;
  }
  return o;
}

String makeDeviceId() {
  uint8_t mac[6] = {};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char buf[13];
  snprintf(buf, sizeof(buf), "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2],
           mac[3], mac[4], mac[5]);
  return String(buf);
}

String scanOptionsHtml() {
  String html;
  const int n = WiFi.scanNetworks(/*async=*/false, /*hidden=*/true);
  if (n <= 0) {
    html += "<option value=\"\">(未扫到网络，可手动输入)</option>";
    return html;
  }
  for (int i = 0; i < n; ++i) {
    String ssid = WiFi.SSID(i);
    if (!ssid.length()) continue;
    html += "<option value=\"";
    html += htmlEscape(ssid);
    html += "\">";
    html += htmlEscape(ssid);
    html += " (";
    html += String(WiFi.RSSI(i));
    html += "dBm)";
    html += WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? " open" : "";
    html += "</option>";
  }
  WiFi.scanDelete();
  return html;
}

String pageHtml() {
  String page;
  page.reserve(3500);
  page += F(
      "<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8>"
      "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
      "<title>RLCD WiFi 配置</title><style>"
      "body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;"
      "background:#0e1218;color:#e7ecf4;padding:24px}"
      ".card{max-width:420px;margin:0 auto;background:#171d27;border:1px solid #2a3344;"
      "border-radius:14px;padding:20px}"
      "h1{font-size:1.25rem;margin:0 0 8px}p{color:#8b95a8;font-size:.9rem}"
      "label{display:block;margin:14px 0 6px;color:#8b95a8;font-size:.82rem}"
      "input,select{width:100%;box-sizing:border-box;padding:12px;border-radius:10px;"
      "border:1px solid #2a3344;background:#0f141d;color:#e7ecf4;font:inherit}"
      "button{margin-top:16px;width:100%;padding:12px;border:0;border-radius:10px;"
      "background:#c4a35a;color:#1a1408;font-weight:700;font:inherit}"
      ".ok{color:#3ecf8e}.err{color:#ef6b7b}.mono{font-family:ui-monospace,monospace;"
      "font-size:.8rem;color:#8b95a8}"
      "</style></head><body><div class=card>");
  page += F("<h1>RLCD WiFi 配置</h1>");
  page += "<p class=mono>AP: ";
  page += htmlEscape(apSsid);
  page += " · 设备 ";
  page += deviceId;
  page += "</p>";
  if (statusMsg.length()) {
    page += "<p class=ok>";
    page += htmlEscape(statusMsg);
    page += "</p>";
  }
  page += F(
      "<form method=POST action=/save>"
      "<label>附近 WiFi</label><select name=ssid_sel id=ssid_sel>"
      "<option value=\"\">-- 选择或下方手输 --</option>");
  page += scanOptionsHtml();
  page += F(
      "</select>"
      "<label>SSID（可手改）</label>"
      "<input name=ssid id=ssid autocomplete=off>"
      "<label>密码</label>"
      "<input name=pass type=password autocomplete=current-password>"
      "<button type=submit>保存并连接</button></form>"
      "<p><a href=/ style=color:#c4a35a>刷新扫描</a></p>"
      "<script>"
      "document.getElementById('ssid_sel').onchange=function(){"
      " if(this.value) document.getElementById('ssid').value=this.value;};"
      "</script></div></body></html>");
  return page;
}

void sendPortal() { server.send(200, "text/html; charset=utf-8", pageHtml()); }

void sendRedirectRoot() {
  server.sendHeader("Location", String("http://") + WiFi.softAPIP().toString() + "/",
                    true);
  server.send(302, "text/plain", "");
}

void handleSave() {
  String ssid = server.arg("ssid");
  ssid.trim();
  if (!ssid.length()) ssid = server.arg("ssid_sel");
  ssid.trim();
  String pass = server.arg("pass");

  if (!ssid.length()) {
    statusMsg = "SSID 不能为空";
    sendPortal();
    return;
  }
  if (!wifiStoreSave(ssid, pass)) {
    statusMsg = "保存失败";
    sendPortal();
    return;
  }

  statusMsg = "已保存，正在连接 " + ssid + " …";
  server.send(200, "text/html; charset=utf-8",
              String(F("<!DOCTYPE html><html lang=zh-CN><meta charset=utf-8>"
                       "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
                       "<body style=\"font-family:sans-serif;background:#0e1218;color:#e7ecf4;"
                       "padding:24px\"><h2>已保存</h2><p>设备将断开热点并连接 ")) +
                  htmlEscape(ssid) +
                  F("</p><p>请回到家里的 WiFi。</p></body></html>"));
  delay(400);
  done = true;
}

void handleNotFound() { sendPortal(); }
}  // namespace

bool wifiApProvision(uint32_t timeoutMs) {
  done = false;
  statusMsg = "";
  deviceId = makeDeviceId();
  apSsid = String("OC-Setup-") + deviceId.substring(8);

  WiFi.persistent(false);
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(apSsid.c_str(), "12345678");
  delay(200);
  const IPAddress ip = WiFi.softAPIP();
  Serial.printf("[ap-prov] SoftAP %s  pass=12345678  http://%s/\n",
                apSsid.c_str(), ip.toString().c_str());

  dns.start(53, "*", ip);

  server.on("/", HTTP_GET, sendPortal);
  server.on("/save", HTTP_POST, handleSave);
  server.on("/generate_204", HTTP_GET, sendRedirectRoot);
  server.on("/gen_204", HTTP_GET, sendRedirectRoot);
  server.on("/hotspot-detect.html", HTTP_GET, sendPortal);
  server.on("/library/test/success.html", HTTP_GET, sendPortal);
  server.on("/ncsi.txt", HTTP_GET, sendRedirectRoot);
  server.on("/connecttest.txt", HTTP_GET, sendRedirectRoot);
  server.on("/fwlink/", HTTP_GET, sendRedirectRoot);
  server.onNotFound(handleNotFound);
  server.begin();

  const uint32_t start = millis();
  while (!done) {
    dns.processNextRequest();
    server.handleClient();
    if (timeoutMs && millis() - start > timeoutMs) {
      Serial.println("[ap-prov] timeout");
      break;
    }
    delay(2);
  }

  server.stop();
  dns.stop();
  WiFi.softAPdisconnect(true);
  return done;
}
