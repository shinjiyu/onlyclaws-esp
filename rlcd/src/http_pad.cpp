#include "http_pad.h"

#include <WiFi.h>
#include <ctype.h>
#include <string.h>

#include "pad_ctrl.h"

namespace {

WiFiServer *gSrv = nullptr;
uint16_t gPort = 80;

// Compact mobile D-pad; relative fetch works for any browser.
const char kPage[] = R"HTML(<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<title>Snake</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;min-height:100vh;background:linear-gradient(165deg,#152018,#0c1210);color:#e8f0ea;
font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
justify-content:space-between;padding:max(16px,env(safe-area-inset-top)) 16px max(24px,env(safe-area-inset-bottom));user-select:none;touch-action:none}
h1{margin:0;font-size:2rem}p{color:#8aa090;text-align:center}
.pad{display:grid;grid-template-columns:repeat(3,22vw);grid-template-rows:repeat(3,22vw);gap:12px;max-width:300px}
button{border:0;border-radius:16px;background:#1e2e24;color:#e8f0ea;font-size:1.5rem;font-weight:700}
button:active{background:#3d7a52;transform:scale(.96)}
.u{grid-column:2;grid-row:1}.l{grid-column:1;grid-row:2}.r{grid-column:3;grid-row:2}.d{grid-column:2;grid-row:3}
.row{display:flex;gap:12px;width:min(300px,100%)}
.row button{flex:1;padding:14px;font-size:1rem;background:#c45c4a}
</style></head><body>
<h1>Snake</h1>
<p>局域网直控 · 任意浏览器</p>
<div class="pad">
<button class="u" data-d="U">▲</button>
<button class="l" data-d="L">◀</button>
<button class="r" data-d="R">▶</button>
<button class="d" data-d="D">▼</button>
</div>
<div class="row"><button id="rst">重新开始</button></div>
<script>
async function go(d){try{await fetch('/d?d='+d,{method:'POST',cache:'no-store'})}catch(e){}}
async function rst(){try{await fetch('/r',{method:'POST',cache:'no-store'})}catch(e){}}
document.querySelector('.pad').ontouchstart=document.querySelector('.pad').onpointerdown=e=>{
  const b=e.target.closest('button[data-d]'); if(!b)return; e.preventDefault(); go(b.dataset.d);
};
document.getElementById('rst').onclick=rst;
</script>
</body></html>)HTML";

char parseDir(char c) {
  c = (char)toupper((unsigned char)c);
  if (c == 'U' || c == 'D' || c == 'L' || c == 'R') return c;
  return 0;
}

void sendAll(WiFiClient &c, const char *hdr, const char *body, size_t n) {
  c.print(hdr);
  c.print("Content-Length: ");
  c.println((unsigned)n);
  c.println("Connection: close");
  c.println();
  c.write((const uint8_t *)body, n);
}

void sendProgmemPage(WiFiClient &c) {
  const size_t n = sizeof(kPage) - 1;
  c.print(
      "HTTP/1.1 200 OK\r\n"
      "Content-Type: text/html; charset=utf-8\r\n"
      "Cache-Control: no-store\r\n"
      "Content-Length: ");
  c.print((unsigned)n);
  c.print("\r\nConnection: close\r\n\r\n");
  c.write((const uint8_t *)kPage, n);
}

void handleClient(WiFiClient c) {
  c.setTimeout(800);
  String req = c.readStringUntil('\n');
  // drain headers
  while (c.connected()) {
    String line = c.readStringUntil('\n');
    if (line.length() <= 2) break;  // \r or empty
  }

  padCtrlSetLink(true);

  if (req.startsWith("GET / ") || req.startsWith("GET /index") || req.startsWith("GET /?")) {
    sendProgmemPage(c);
  } else if (req.indexOf(" /d") >= 0) {
    // /d?d=U  or /d?d=U HTTP
    char d = 0;
    int i = req.indexOf("d=");
    if (i >= 0 && (size_t)i + 2 < req.length()) d = parseDir(req.charAt(i + 2));
    if (d) {
      padCtrlSetDir(d);
      Serial.printf("[http-pad] dir=%c\n", d);
    }
    const char *body = "{\"ok\":true}";
    sendAll(c,
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n",
            body, strlen(body));
  } else if (req.indexOf(" /r") >= 0) {
    padCtrlRequestRestart();
    Serial.println("[http-pad] restart");
    const char *body = "{\"ok\":true}";
    sendAll(c,
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n",
            body, strlen(body));
  } else if (req.indexOf(" /health") >= 0) {
    const char *body = "{\"ok\":true}";
    sendAll(c,
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n",
            body, strlen(body));
  } else {
    const char *body = "not found";
    sendAll(c, "HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n", body, strlen(body));
  }
  c.stop();
}

void httpPadTask(void *) {
  for (;;) {
    if (gSrv) {
      WiFiClient c = gSrv->available();
      if (c) handleClient(c);
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

}  // namespace

void httpPadBegin(uint16_t port) {
  if (gSrv) return;
  gPort = port ? port : 80;
  gSrv = new WiFiServer(gPort);
  gSrv->begin();
  gSrv->setNoDelay(true);
  xTaskCreatePinnedToCore(httpPadTask, "http-pad", 8192, nullptr, 1, nullptr, 0);
  Serial.printf("[http-pad] http://%s:%u/\n", WiFi.localIP().toString().c_str(), (unsigned)gPort);
}

void httpPadLoop() {
  // handled in task
}
