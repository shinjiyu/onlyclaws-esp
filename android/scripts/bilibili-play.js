var KEY = "";

var ALLOW = {
  home: true, refresh: true, scroll: true, open: true, read: true, comments: true,
  space: false, search: false, pause: false, seek: false,
  like: false, unlike: false, coin: false, fav: false, unfav: false,
  follow: false, unfollow: false, commentLike: false,
  comment: false, reply: false, danmaku: false
};
var CAP = {
  home: 30, refresh: 20, scroll: 120, open: 40, read: 40, comments: 20,
  space: 10, search: 10, pause: 30, seek: 10,
  like: 10, unlike: 10, coin: 5, fav: 5, unfav: 5,
  follow: 3, unfollow: 3, commentLike: 10,
  comment: 2, reply: 2, danmaku: 2
};
var NAMES = {
  home: "打开推荐", refresh: "刷新", scroll: "向下滑", open: "点进视频",
  read: "读标题", comments: "看评论", space: "打开主页", search: "搜索",
  pause: "暂停", seek: "拖进度", like: "点赞", unlike: "取消点赞",
  coin: "投币", fav: "收藏", unfav: "取消收藏", follow: "关注",
  unfollow: "取消关注", commentLike: "给评论点赞", comment: "发评论",
  reply: "回复", danmaku: "发弹幕"
};

var wait = 0;
var hour = "";
var used = {};
var minute = "";
var tokens = 0;
var done = {};
var blockedSwitch = {};
var blockedCap = {};

var GAP_MIN = 30;
var GAP_MAX = 600;
var GAP_STEP = 30;
var gap = 60;
var promptId = "curious";
var customPrompt = "";
var PRESETS = [
  { id: "curious", text: "你天生好奇" },
  { id: "stay", text: "你喜欢看完再走" },
  { id: "skim", text: "你只是随便看看" }
];

var LOGIN = "https://passport.bilibili.com/h5-app/passport/login";
var hold = false;
var running = false;
var checking = false;
var fault = "";
var jump = "";
var timeline = [];
var ORDER = ["home","refresh","scroll","open","read","comments","space","search","pause","seek","like","unlike","coin","fav","unfav","follow","unfollow","commentLike","comment","reply","danmaku"];
var GROUP = {
  home: "浏览", refresh: "浏览", scroll: "浏览", open: "浏览", read: "浏览", comments: "浏览",
  space: "浏览", search: "浏览", pause: "播放", seek: "播放",
  like: "互动", unlike: "互动", coin: "互动", fav: "互动", unfav: "互动",
  follow: "互动", unfollow: "互动", commentLike: "互动", comment: "互动", reply: "互动", danmaku: "互动"
};

function rememberKey() {
  var saved = "";
  try { saved = String(keys.get("deepseek") || ""); } catch (err) { saved = ""; }
  KEY = saved;
}

function snapGap(n) {
  var value = Math.round(n / GAP_STEP) * GAP_STEP;
  if (value < GAP_MIN) value = GAP_MIN;
  if (value > GAP_MAX) value = GAP_MAX;
  return value;
}

function gapWords(n) {
  if (n < 60) return n + " 秒";
  var minutes = Math.floor(n / 60);
  var rest = n % 60;
  if (!rest) return minutes + " 分钟";
  return minutes + " 分 " + rest + " 秒";
}

function presetText(id) {
  for (var i = 0; i < PRESETS.length; i++) {
    if (PRESETS[i].id === id) return PRESETS[i].text;
  }
  return "";
}

function persona() {
  if (promptId === "custom" && customPrompt) return customPrompt;
  return presetText(promptId) || "你天生好奇";
}

function rememberPrefs() {
  var savedGap = 0;
  var savedId = "";
  var savedText = "";
  try { savedGap = parseInt(keys.get("gap") || "0", 10); } catch (err) { savedGap = 0; }
  try { savedId = String(keys.get("prompt") || ""); } catch (err2) { savedId = ""; }
  try { savedText = String(keys.get("prompt_text") || ""); } catch (err3) { savedText = ""; }
  if (savedGap >= GAP_MIN && savedGap <= GAP_MAX) gap = snapGap(savedGap);
  if (savedText) customPrompt = savedText;
  if (savedId === "custom" || presetText(savedId)) promptId = savedId;
  var savedTokens = 0;
  try { savedTokens = parseInt(keys.get("tokens_used") || "0", 10); } catch (err4) { savedTokens = 0; }
  if (savedTokens > 0) tokens = savedTokens;
}

function onStart() {
  oca.log("play agent 已装上");
  rememberKey();
  rememberPrefs();
  hold = !!web.loggedIn();
  running = false;
  note(hold ? "已经登录" : "等待登录");
  if (!hold) web.url(LOGIN);
}

function onFrame(dt) {
  if (web.loggedIn()) {
    if (!hold) {
      hold = true;
      if (fault === "还没登录 B 站") fault = "";
      if (web.showing()) web.clear();
      note("登录成功，页面已收起");
    }
  }
  if (!running) return;
  wait += dt;
  if (wait < gap) return;
  wait = 0;
  try {
    step();
  } catch (err) {
    oca.log(String(err).slice(0, 160));
  }
  paint();
}

function onAction(e) {
  var id = e && e.id ? String(e.id) : "";
  if (id === "login") {
    hold = false;
    web.url(LOGIN);
    return;
  }
  if (id === "start") {
    if (checking) return;
    rememberKey();
    if (!KEY) {
      fail("还没保存 API Key", "配置");
      return;
    }
    checking = true;
    fault = "";
    paint();
    var problem = "";
    try {
      problem = checkKey();
    } catch (err4) {
      problem = String(err4).slice(0, 80);
    }
    checking = false;
    if (problem) {
      fail(problem, problem.indexOf("API Key") >= 0 ? "配置" : "运行");
      return;
    }
    if (!web.loggedIn()) {
      hold = false;
      web.url(LOGIN);
      fail("还没登录 B 站", "运行");
      return;
    }
    running = true;
    fault = "";
    note("检查通过，开始");
    return;
  }
  if (id === "stop") {
    running = false;
    if (web.showing()) web.clear();
    note("结束");
    return;
  }
  if (id === "key") {
    var value = e && e.value ? String(e.value).replace(/^\s+|\s+$/g, "") : "";
    if (!value || value.length > 400) {
      note("密钥空的");
      return;
    }
    var wrote = false;
    try { wrote = !!keys.set("deepseek", value); } catch (err3) { wrote = false; }
    if (!wrote) {
      note("密钥没写下");
      return;
    }
    KEY = value;
    if (fault.indexOf("API Key") >= 0) fault = "";
    note("密钥已保存");
    return;
  }
  if (id === "gap") {
    var n = parseInt(e && e.value ? e.value : "", 10);
    if (!(n >= GAP_MIN && n <= GAP_MAX)) return;
    n = snapGap(n);
    if (n === gap) {
      paint();
      return;
    }
    gap = n;
    try { keys.set("gap", String(n)); } catch (err5) {}
    note("外层间隔改成 " + gapWords(n));
    return;
  }
  if (id === "promptText") {
    var typed = String(e && e.value ? e.value : "").replace(/[\r\n]+/g, " ").replace(/^\s+|\s+$/g, "");
    if (!typed) {
      note("提示词是空的");
      return;
    }
    if (typed.length > 400) typed = typed.slice(0, 400);
    var wrotePrompt = false;
    try { wrotePrompt = !!keys.set("prompt_text", typed) && !!keys.set("prompt", "custom"); } catch (err6) { wrotePrompt = false; }
    if (!wrotePrompt) {
      note("提示词没写下");
      return;
    }
    customPrompt = typed;
    promptId = "custom";
    note("提示词已保存");
    return;
  }
  if (id === "custom" || presetText(id)) {
    if (id !== promptId) {
      promptId = id;
      try { keys.set("prompt", id); } catch (err7) {}
      note(id === "custom" ? "改用自己的提示词" : ("提示词换成 " + presetText(id)));
      return;
    }
    paint();
    return;
  }
  if (!CAP[id]) return;
  ALLOW[id] = !ALLOW[id];
  note((ALLOW[id] ? "打开 " : "关上 ") + (NAMES[id] || id));
}

function keyReady() {
  try { return !!keys.has("deepseek"); } catch (err) { return false; }
}

function checkKey() {
  var res = http.request({
    url: "https://api.deepseek.com/v1/models",
    method: "GET",
    headers: { Authorization: "Bearer " + KEY },
    timeoutMs: 20000
  });
  if (!res || res.error) return res && res.error ? res.error : "没有结果";
  if (res.status === 401 || res.status === 403) return "API Key 无效";
  if (res.status < 200 || res.status >= 300) return "模型 HTTP " + res.status;
  return "";
}

function fail(message, where) {
  fault = message;
  jump = where || "运行";
  oca.log(message);
  note(message);
}

function note(text) {
  var now = new Date();
  var hh = now.getHours();
  var mm = now.getMinutes();
  var stamp = (hh < 10 ? "0" : "") + hh + ":" + (mm < 10 ? "0" : "") + mm;
  timeline.unshift({ time: stamp, text: text });
  if (timeline.length > 20) timeline.length = 20;
  paint();
}

function paint() {
  var rows = [];
  for (var i = 0; i < ORDER.length; i++) {
    var id = ORDER[i];
    rows.push({
      id: id,
      name: NAMES[id] || id,
      group: GROUP[id] || "",
      on: !!ALLOW[id],
      used: used[id] || 0,
      cap: CAP[id] || 0
    });
  }
  try {
    desk.show({
      title: "逛 B 站",
      status: (web.loggedIn() ? "已登录" : "还没登录") + " · " + (checking ? "正在检查" : (running ? "进行中" : "已停下")),
      login: web.loggedIn() ? "" : "登录 B 站",
      running: running,
      keyReady: keyReady(),
      error: fault,
      checking: checking,
      open: (function () { var page = jump; jump = ""; return page; })(),
      tokens: tokens,
      tokenCap: 20000,
      rows: rows,
      stats: [
        { name: "已做", value: String(total(done)) },
        { name: "开关挡住", value: String(total(blockedSwitch)) },
        { name: "到上限", value: String(total(blockedCap)) }
      ],
      gap: gap,
      gapMin: GAP_MIN,
      gapMax: GAP_MAX,
      gapStep: GAP_STEP,
      prompts: PRESETS,
      prompt: promptId,
      custom: customPrompt,
      events: timeline
    });
  } catch (err) {
    oca.log(String(err).slice(0, 160));
  }
}

function total(map) {
  var n = 0;
  for (var k in map) n += map[k] || 0;
  return n;
}

function step() {
  var seen = page();
  var allowed = [];
  for (var name in ALLOW) {
    if (ALLOW[name]) allowed.push(name);
  }
  var ask = "Begin.\n当前页面：" + seen +
    "\n现在可以做的动作：" + allowed.join(" ") +
    "\n只回复一个 JSON，形如 {\"behavior\":\"一句你正在做的事\",\"action\":\"scroll\"}。behavior 用一句中文。action 必须是上面其中一个。";
  var res = http.request({
    url: "https://api.deepseek.com/v1/chat/completions",
    method: "POST",
    headers: {
      Authorization: "Bearer " + KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: "deepseek-flash",
      messages: [
        { role: "system", content: persona() },
        { role: "user", content: ask }
      ],
      max_tokens: 200,
      temperature: 0.5
    }),
    timeoutMs: 60000
  });
  if (!res || res.error) {
    oca.log("模型 " + (res && res.error ? res.error : "没有结果"));
    return;
  }
  if (res.status < 200 || res.status >= 300) {
    oca.log("模型 HTTP " + res.status + " " + String(res.body || "").slice(0, 80));
    return;
  }
  noteTokens(res.body);
  var action = pick(res.body);
  var said = behaviorOf(res.body);
  if (!action || !CAP[action]) {
    oca.log(said || "没认出动作");
    return;
  }
  if (!take(action)) return;
  run(action);
  if (said) {
    oca.log(said);
    note(said);
  }
}

function page() {
  var raw = web.eval("(function(){try{var as=[].slice.call(document.querySelectorAll('a[href*=\"/video/\"]'),0,6).map(function(a){return (a.innerText||'').replace(/\\s+/g,' ').trim().slice(0,40);}).filter(Boolean); return JSON.stringify({title:document.title,url:location.href,videos:as});}catch(e){return JSON.stringify({err:String(e)});}})()");
  return unwrap(raw).slice(0, 500);
}

function unwrap(raw) {
  if (!raw) return "";
  try {
    var value = JSON.parse(raw);
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  } catch (err) {
    return String(raw);
  }
}

function noteTokens(body) {
  try {
    var data = JSON.parse(body);
    var n = data.usage && (data.usage.total_tokens || 0);
    if (n) tokens += n;
  } catch (err) {}
  try { keys.set("tokens_used", String(tokens)); } catch (err2) {}
}

function messageText(body) {
  try {
    return JSON.parse(body).choices[0].message.content || "";
  } catch (err) {
    return "";
  }
}

function behaviorOf(body) {
  var text = messageText(body);
  var start = text.indexOf("{");
  var end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return "";
  try {
    return String(JSON.parse(text.slice(start, end + 1)).behavior || "").replace(/\s+/g, " ").slice(0, 80);
  } catch (err) {
    return "";
  }
}

function pick(body) {
  var text = messageText(body);
  if (!text) return "";
  var start = text.indexOf("{");
  var end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return "";
  try {
    return String(JSON.parse(text.slice(start, end + 1)).action || "");
  } catch (err2) {
    return "";
  }
}

function take(action) {
  if (!ALLOW[action]) {
    blockedSwitch[action] = (blockedSwitch[action] || 0) + 1;
    oca.log(NAMES[action] + " 开关关着");
    return false;
  }
  var now = new Date();
  var key = now.getFullYear() + "-" + now.getMonth() + "-" + now.getDate() + "-" + now.getHours();
  if (key !== hour) {
    hour = key;
    used = {};
  }
  var n = used[action] || 0;
  if (n >= CAP[action]) {
    blockedCap[action] = (blockedCap[action] || 0) + 1;
    oca.log(NAMES[action] + " 这一小时满了");
    return false;
  }
  used[action] = n + 1;
  done[action] = (done[action] || 0) + 1;
  return true;
}

function run(action) {
  if (action === "home") web.url("https://www.bilibili.com");
  else if (action === "refresh") web.eval("location.reload()");
  else if (action === "scroll") web.eval("window.scrollBy(0, Math.round(window.innerHeight*0.85))");
  else if (action === "open") web.eval("(function(){var a=document.querySelector('a[href*=\"/video/\"]'); if(a) a.click();})()");
  else if (action === "read") page();
  else if (action === "comments") web.eval("var n=document.querySelector('#comment')||document.querySelector('.comment-container'); if(n) n.scrollIntoView(); else window.scrollTo(0, document.body.scrollHeight);");
  else if (action === "space") web.eval("(function(){var a=document.querySelector('a[href*=\"space.bilibili.com\"]'); if(a) a.click();})()");
  else if (action === "pause") web.eval("(function(){var v=document.querySelector('video'); if(v){ if(v.paused) v.play(); else v.pause(); }})()");
  else if (action === "like" || action === "coin" || action === "fav" || action === "follow" || action === "comment" || action === "reply" || action === "danmaku") {
    oca.log(NAMES[action] + " 还没接到页面按钮");
  }
}
