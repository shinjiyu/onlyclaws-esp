var MODEL = "deepseek-flash";
var LOGIN = "https://passport.bilibili.com/h5-app/passport/login";
var HOME = "https://www.bilibili.com";
var API = "https://api.bilibili.com";
var UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36";
var LIST_CAP = 8;
var PAGE_CAP = 20;
var TEXT_CAP = 3500;
var TOKEN_CAP = 20000;
var GAP_MIN = 30;
var GAP_MAX = 600;
var GAP_STEP = 30;
var MIXIN = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52];

var TOOLS = [
  { name: "bili_hot", group: "浏览", title: "热门", cap: 30, on: true, need: false,
    desc: "看热门或排行。kind 是 popular 或 ranking。page 从 1 起。ranking 忽略 page。",
    props: { kind: { type: "string", enum: ["popular", "ranking"], description: "popular 或 ranking。默认 popular。" }, page: { type: "number", description: "页码，从 1 起。" } },
    required: [] },
  { name: "bili_search", group: "浏览", title: "搜索", cap: 10, on: true, need: false,
    desc: "按关键词搜视频。page 从 1 起。",
    props: { keyword: { type: "string", description: "搜索词。" }, page: { type: "number", description: "页码，从 1 起。" } },
    required: ["keyword"] },
  { name: "bili_video", group: "浏览", title: "打开视频", cap: 40, on: true, need: false,
    desc: "打开一个视频。返回标题、简介、作者、时长和公开数据。owner_mid 是作者编号。不播文件。",
    props: { bvid: { type: "string", description: "视频 id，如 BV1xx411c7mD。" } },
    required: ["bvid"] },
  { name: "bili_read", group: "浏览", title: "读内容", cap: 40, on: true, need: false,
    desc: "读视频在说什么。先用 B 站总结和提纲，没有再给中文字幕。from 是字幕起始秒。source 为 none 时，用简介和 bili_comments。不下载、不看画面。",
    props: { bvid: { type: "string", description: "视频 id。" }, from: { type: "number", description: "字幕起始秒。省略则从总结开始。" } },
    required: ["bvid"] },
  { name: "bili_comments", group: "浏览", title: "看评论", cap: 20, on: true, need: false,
    desc: "读评论。sort 是 hot 或 new。cursor 是上一页的 next。",
    props: { bvid: { type: "string", description: "视频 id。" }, sort: { type: "string", enum: ["hot", "new"], description: "hot 或 new。默认 hot。" }, cursor: { type: "number", description: "上一页的 next。省略则从头。" } },
    required: ["bvid"] },
  { name: "bili_related", group: "浏览", title: "相关推荐", cap: 20, on: true, need: false,
    desc: "这个视频旁边的推荐。",
    props: { bvid: { type: "string", description: "视频 id。" } },
    required: ["bvid"] },
  { name: "bili_space", group: "浏览", title: "作者主页", cap: 10, on: true, need: false,
    desc: "一个作者最近的公开视频。mid 是 bili_video 返回的 owner_mid。",
    props: { mid: { type: "number", description: "作者编号。" }, page: { type: "number", description: "页码，从 1 起。" } },
    required: ["mid"] },
  { name: "bili_me", group: "帐号", title: "我的帐号", cap: 20, on: true, need: false,
    desc: "这个帐号的名字、等级和还剩多少硬币。",
    props: {}, required: [] },
  { name: "bili_feed", group: "帐号", title: "关注动态", cap: 10, on: false, need: true,
    desc: "关注的人刚发的动态。offset 来自上一页。",
    props: { offset: { type: "string", description: "上一页的 offset。省略则从头。" } },
    required: [] },
  { name: "bili_history", group: "帐号", title: "观看历史", cap: 10, on: false, need: true,
    desc: "这个帐号看过的视频。max 和 view_at 来自上一页。",
    props: { max: { type: "number", description: "历史游标。" }, view_at: { type: "number", description: "历史时间游标。" } },
    required: [] },
  { name: "bili_favs", group: "帐号", title: "收藏夹", cap: 10, on: false, need: true,
    desc: "收藏夹。不带 media_id 是夹子列表，带上是里面的视频。",
    props: { media_id: { type: "number", description: "收藏夹 id。" }, page: { type: "number", description: "夹内页码，从 1 起。" } },
    required: [] },
  { name: "bili_like", group: "互动", title: "点赞", cap: 10, on: false, need: true,
    desc: "赞或取消赞。action 是 like 或 unlike。",
    props: { bvid: { type: "string", description: "视频 id。" }, action: { type: "string", enum: ["like", "unlike"], description: "like 或 unlike。默认 like。" } },
    required: ["bvid"] },
  { name: "bili_coin", group: "互动", title: "投币", cap: 5, on: false, need: true,
    desc: "投 1 或 2 个硬币，会花掉帐号里的硬币。also_like=true 同时点赞。",
    props: { bvid: { type: "string", description: "视频 id。" }, count: { type: "number", description: "1 或 2。" }, also_like: { type: "boolean", description: "同时点赞。默认 false。" } },
    required: ["bvid", "count"] },
  { name: "bili_fav", group: "互动", title: "收藏", cap: 5, on: false, need: true,
    desc: "放进收藏夹或移出。action 是 add 或 remove。add 时省略 media_id 用默认收藏夹。",
    props: { bvid: { type: "string", description: "视频 id。" }, action: { type: "string", enum: ["add", "remove"], description: "add 或 remove。默认 add。" }, media_id: { type: "number", description: "收藏夹 id。" } },
    required: ["bvid"] },
  { name: "bili_follow", group: "互动", title: "关注", cap: 3, on: false, need: true,
    desc: "关注或取关。mid 是 owner_mid。action 是 follow 或 unfollow。",
    props: { mid: { type: "number", description: "作者编号。" }, action: { type: "string", enum: ["follow", "unfollow"], description: "follow 或 unfollow。默认 follow。" } },
    required: ["mid"] },
  { name: "bili_comment", group: "互动", title: "发评论", cap: 2, on: false, need: true,
    desc: "发一条公开评论，或用 reply_to 回复某条 rpid。最多 300 字。",
    props: { bvid: { type: "string", description: "视频 id。" }, text: { type: "string", description: "评论，最多 300 字。" }, reply_to: { type: "number", description: "要回复的 rpid。" } },
    required: ["bvid", "text"] },
  { name: "bili_toview", group: "互动", title: "稍后再看", cap: 5, on: false, need: true,
    desc: "放进稍后再看。",
    props: { bvid: { type: "string", description: "视频 id。" } },
    required: ["bvid"] }
];

var PRESETS = [
  { id: "curious", text: "你天生好奇" },
  { id: "stay", text: "你喜欢看完再走" },
  { id: "skim", text: "你只是随便看看" }
];

var KEY = "";
var ALLOW = {};
var CAP = {};
var NAMES = {};
var GROUP = {};
var ORDER = [];
(function seedTools() {
  for (var i = 0; i < TOOLS.length; i++) {
    var tool = TOOLS[i];
    ALLOW[tool.name] = !!tool.on;
    CAP[tool.name] = tool.cap;
    NAMES[tool.name] = tool.title;
    GROUP[tool.name] = tool.group;
    ORDER.push(tool.name);
  }
})();

var wait = 0;
var hour = "";
var used = {};
var tokens = 0;
var done = {};
var blockedSwitch = {};
var blockedCap = {};
var gap = 60;
var promptId = "curious";
var customPrompt = "";
var hold = false;
var running = false;
var checking = false;
var busy = false;
var fault = "";
var jump = "";
var timeline = [];
var history = [];
var idleStreak = 0;
var wbiCache = null;

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
  else holdBrowsePage();
}

function onFrame(dt) {
  if (web.loggedIn()) {
    if (!hold) {
      hold = true;
      if (fault === "还没登录 B 站") fault = "";
      holdBrowsePage();
      note("登录成功，页面留在后台");
    }
  }
  if (!running || busy) return;
  wait += dt;
  if (wait < gap) return;
  wait = 0;
  busy = true;
  try {
    step();
  } catch (err) {
    oca.log(String(err).slice(0, 160));
  }
  busy = false;
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
    if (checking || busy) return;
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
    holdBrowsePage();
    running = true;
    fault = "";
    history = [{ role: "user", content: "Begin." }];
    idleStreak = 0;
    wait = gap;
    note("检查通过，开始");
    return;
  }
  if (id === "stop") {
    running = false;
    busy = false;
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
      tokenCap: TOKEN_CAP,
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

function toolCard() {
  var lines = ["你在逛 B 站，用的是这台手机已经登录的帐号。轮与轮之间有间隔，不用自己等待。工具只有这些："];
  for (var i = 0; i < TOOLS.length; i++) {
    var tool = TOOLS[i];
    if (!ALLOW[tool.name]) continue;
    lines.push("- " + tool.name + "：" + tool.desc);
  }
  lines.push("赞、投币、收藏、关注、评论、稍后再看都算在这个帐号上。评论发出去是公开的。");
  lines.push(persona());
  return lines.join("\n");
}

function schema() {
  var out = [];
  for (var i = 0; i < TOOLS.length; i++) {
    var tool = TOOLS[i];
    if (!ALLOW[tool.name]) continue;
    var fn = {
      name: tool.name,
      description: tool.desc,
      parameters: { type: "object", properties: tool.props }
    };
    if (tool.required && tool.required.length) fn.parameters.required = tool.required;
    out.push({ type: "function", function: fn });
  }
  return out;
}

function step() {
  if (!schema().length) {
    oca.log("没有打开的工具");
    return;
  }
  history = wire(history, 8);
  var messages = history.slice();
  if (!messages.length) {
    messages.push({ role: "user", content: "Begin." });
    history = messages.slice();
  }
  var body = {
    model: MODEL,
    messages: [{ role: "system", content: toolCard() }].concat(messages),
    tools: schema(),
    tool_choice: "auto",
    max_tokens: 800,
    temperature: 0.5,
    thinking: { type: "disabled" }
  };
  var res = http.request({
    url: "https://api.deepseek.com/v1/chat/completions",
    method: "POST",
    headers: {
      Authorization: "Bearer " + KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body),
    timeoutMs: 60000
  });
  if (!res || res.error) {
    oca.log("模型 " + (res && res.error ? res.error : "没有结果"));
    return;
  }
  if (res.status < 200 || res.status >= 300) {
    var errText = String(res.body || "").replace(/\s+/g, " ").slice(0, 180);
    oca.log("模型 HTTP " + res.status + " " + errText);
    if (res.status === 400) history = wire(history, 4);
    return;
  }
  noteTokens(res.body);
  var msg = messageOf(res.body);
  var calls = msg.calls;
  var said = msg.content;
  if (!calls.length) {
    if (said) {
      oca.log(said);
      note(said);
      history.push({ role: "assistant", content: said });
    } else {
      oca.log("这一轮没有动作");
    }
    idleStreak += 1;
    if (idleStreak >= 2) {
      history.push({ role: "user", content: "继续逛。" });
      idleStreak = 0;
    }
    return;
  }
  idleStreak = 0;
  var assistant = { role: "assistant", content: said || null, tool_calls: [] };
  var names = [];
  for (var i = 0; i < calls.length; i++) {
    assistant.tool_calls.push({
      id: String(calls[i].id || ("call_" + i)),
      type: "function",
      function: { name: calls[i].name, arguments: JSON.stringify(calls[i].args || {}) }
    });
  }
  history.push(assistant);
  for (var j = 0; j < calls.length; j++) {
    var call = calls[j];
    names.push(call.name);
    var result = runTool(call.name, call.args);
    history.push({ role: "tool", tool_call_id: call.id, content: JSON.stringify(result) });
    if (result.ok) note((NAMES[call.name] || call.name) + (said && j === 0 ? " · " + said : ""));
    else oca.log((NAMES[call.name] || call.name) + " " + String(result.output || "").slice(0, 80));
  }
  if (said) oca.log(said);
  oca.log(names.join(", "));
}

function wire(list, keep) {
  var turns = [];
  var i = 0;
  while (i < list.length) {
    var msg = list[i];
    if (!msg || msg.role === "tool") {
      i += 1;
      continue;
    }
    if (msg.role === "assistant" && msg.tool_calls && msg.tool_calls.length) {
      var need = {};
      var left = 0;
      var calls = [];
      for (var t = 0; t < msg.tool_calls.length; t++) {
        var call = msg.tool_calls[t];
        var id = String(call && call.id ? call.id : "");
        if (!id || need[id]) continue;
        need[id] = true;
        calls.push(call);
        left += 1;
      }
      var tools = [];
      var j = i + 1;
      while (j < list.length && list[j] && list[j].role === "tool") {
        var tid = String(list[j].tool_call_id || "");
        if (need[tid]) {
          tools.push({
            role: "tool",
            tool_call_id: tid,
            content: list[j].content == null ? "" : String(list[j].content)
          });
          delete need[tid];
          left -= 1;
        }
        j += 1;
      }
      if (left === 0 && calls.length) {
        turns.push([{
          role: "assistant",
          content: msg.content || null,
          tool_calls: calls
        }].concat(tools));
      }
      i = j;
      continue;
    }
    turns.push([msg]);
    i += 1;
  }
  if (keep && turns.length > keep) turns = turns.slice(turns.length - keep);
  var out = [];
  for (var k = 0; k < turns.length; k++) {
    for (var n = 0; n < turns[k].length; n++) out.push(turns[k][n]);
  }
  return out;
}

function messageOf(raw) {
  var empty = { content: "", calls: [] };
  try {
    var choice = JSON.parse(raw).choices[0].message;
    var content = textOf(choice.content);
    var calls = [];
    var list = choice.tool_calls;
    if (list && list.length) {
      for (var i = 0; i < list.length; i++) {
        var item = list[i];
        var fn = item.function || {};
        calls.push({
          id: String(item.id || ("call_" + i)),
          name: String(fn.name || ""),
          args: parseArgs(fn.arguments)
        });
      }
    }
    return { content: content, calls: calls };
  } catch (err) {
    return empty;
  }
}

function textOf(value) {
  if (value == null) return "";
  if (typeof value === "string") return value.replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "");
  if (value && value.length) {
    var parts = [];
    for (var i = 0; i < value.length; i++) {
      if (typeof value[i] === "string") parts.push(value[i]);
      else if (value[i] && value[i].text) parts.push(String(value[i].text));
    }
    return parts.join(" ").replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "");
  }
  return String(value);
}

function parseArgs(raw) {
  if (!raw) return {};
  if (typeof raw === "object") return raw;
  try {
    var parsed = JSON.parse(String(raw));
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (err) {
    return {};
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

function take(name) {
  if (!ALLOW[name]) {
    blockedSwitch[name] = (blockedSwitch[name] || 0) + 1;
    return err((NAMES[name] || name) + " 开关关着");
  }
  var now = new Date();
  var key = now.getFullYear() + "-" + now.getMonth() + "-" + now.getDate() + "-" + now.getHours();
  if (key !== hour) {
    hour = key;
    used = {};
  }
  var n = used[name] || 0;
  if (n >= (CAP[name] || 0)) {
    blockedCap[name] = (blockedCap[name] || 0) + 1;
    return err((NAMES[name] || name) + " 这一小时满了");
  }
  used[name] = n + 1;
  done[name] = (done[name] || 0) + 1;
  return null;
}

function err(text) {
  return { ok: false, output: text };
}

function ok(value) {
  return { ok: true, output: JSON.stringify(value) };
}

function runTool(name, args) {
  var blocked = take(name);
  if (blocked) return blocked;
  try {
    if (name === "bili_hot") return biliHot(args);
    if (name === "bili_search") return biliSearch(args);
    if (name === "bili_video") return biliVideo(args);
    if (name === "bili_read") return biliRead(args);
    if (name === "bili_comments") return biliComments(args);
    if (name === "bili_related") return biliRelated(args);
    if (name === "bili_space") return biliSpace(args);
    if (name === "bili_me") return biliMe();
    if (name === "bili_feed") return biliFeed(args);
    if (name === "bili_history") return biliHistory(args);
    if (name === "bili_favs") return biliFavs(args);
    if (name === "bili_like") return biliLike(args);
    if (name === "bili_coin") return biliCoin(args);
    if (name === "bili_fav") return biliFav(args);
    if (name === "bili_follow") return biliFollow(args);
    if (name === "bili_comment") return biliComment(args);
    if (name === "bili_toview") return biliToview(args);
    return err("Unknown tool: " + name);
  } catch (e) {
    return err(String(e).slice(0, 160));
  }
}

function parseBvid(value) {
  var bvid = String(value == null ? "" : value).replace(/^\s+|\s+$/g, "");
  return /^BV[0-9A-Za-z]{10}$/.test(bvid) ? bvid : "";
}

function pageNum(value) {
  if (value == null || value === "") return 1;
  var page = Number(value);
  if (!isFinite(page) || page !== Math.floor(page) || page < 1 || page > PAGE_CAP) return 0;
  return page;
}

function clock(seconds) {
  var total = Math.max(0, Math.floor(Number(seconds) || 0));
  var hour = Math.floor(total / 3600);
  var minute = Math.floor((total % 3600) / 60);
  var second = total % 60;
  var mm = (minute < 10 ? "0" : "") + minute;
  var ss = (second < 10 ? "0" : "") + second;
  return hour > 0 ? hour + ":" + mm + ":" + ss : mm + ":" + ss;
}

function stripHtml(value) {
  return String(value == null ? "" : value)
    .replace(/<[^>]+>/g, "")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .replace(/^\s+|\s+$/g, "");
}

function cardFromArchive(item) {
  if (!item || typeof item !== "object") return null;
  var bvid = parseBvid(item.bvid);
  var title = stripHtml(item.title);
  if (!bvid || !title || title === "视频已失效") return null;
  var owner = item.owner || {};
  var stat = item.stat || {};
  var card = {
    bvid: bvid,
    title: title,
    author: String(owner.name || ""),
    duration: clock(item.duration),
    views: Number(stat.view || 0)
  };
  if (item.tname) card.tname = String(item.tname);
  return card;
}

function cookieJar(raw) {
  var jar = {};
  var parts = String(raw || "").split(";");
  for (var i = 0; i < parts.length; i++) {
    var part = parts[i];
    var eq = part.indexOf("=");
    if (eq <= 0) continue;
    var key = part.slice(0, eq).replace(/^\s+|\s+$/g, "");
    var value = part.slice(eq + 1).replace(/^\s+|\s+$/g, "");
    if (key) jar[key] = value;
  }
  return jar;
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

function pageHref() {
  try {
    return unwrap(web.eval("(function(){try{return location.href;}catch(e){return '';}})()"));
  } catch (err) {
    return "";
  }
}

function holdBrowsePage() {
  var href = pageHref();
  if (href.indexOf("bilibili.com") >= 0 && href.indexOf("passport") < 0 && href.indexOf("about:") < 0) return true;
  web.url(HOME);
  return false;
}

function pageCookie() {
  try {
    return unwrap(web.eval("(function(){try{return document.cookie;}catch(e){return '';}})()"));
  } catch (err) {
    return "";
  }
}

function readSession() {
  if (!web.loggedIn()) return null;
  var jar = cookieJar(pageCookie());
  return { csrf: jar.bili_jct || "", mid: jar.DedeUserID || "" };
}

function needLogin() {
  return web.loggedIn() ? null : err("未登录。还没有 B 站登录态。");
}

function md5hex(text) {
  function add(x, y) {
    var lsw = (x & 0xffff) + (y & 0xffff);
    var msw = (x >> 16) + (y >> 16) + (lsw >> 16);
    return (msw << 16) | (lsw & 0xffff);
  }
  function rol(num, cnt) { return (num << cnt) | (num >>> (32 - cnt)); }
  function cmn(q, a, b, x, s, t) { return add(rol(add(add(a, q), add(x, t)), s), b); }
  function ff(a, b, c, d, x, s, t) { return cmn((b & c) | ((~b) & d), a, b, x, s, t); }
  function gg(a, b, c, d, x, s, t) { return cmn((b & d) | (c & (~d)), a, b, x, s, t); }
  function hh(a, b, c, d, x, s, t) { return cmn(b ^ c ^ d, a, b, x, s, t); }
  function ii(a, b, c, d, x, s, t) { return cmn(c ^ (b | (~d)), a, b, x, s, t); }
  function utf8(s) {
    s = String(s).replace(/\r\n/g, "\n");
    var out = "";
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c < 128) out += String.fromCharCode(c);
      else if (c < 2048) out += String.fromCharCode((c >> 6) | 192, (c & 63) | 128);
      else out += String.fromCharCode((c >> 12) | 224, ((c >> 6) & 63) | 128, (c & 63) | 128);
    }
    return out;
  }
  var msg = utf8(text);
  var nblk = ((msg.length + 8) >> 6) + 1;
  var blks = [];
  var i;
  for (i = 0; i < nblk * 16; i++) blks[i] = 0;
  for (i = 0; i < msg.length; i++) blks[i >> 2] |= msg.charCodeAt(i) << ((i % 4) * 8);
  blks[i >> 2] |= 0x80 << ((i % 4) * 8);
  blks[nblk * 16 - 2] = msg.length * 8;
  var a = 1732584193, b = -271733879, c = -1732584194, d = 271733878;
  for (i = 0; i < blks.length; i += 16) {
    var oa = a, ob = b, oc = c, od = d;
    a = ff(a, b, c, d, blks[i + 0], 7, -680876936); d = ff(d, a, b, c, blks[i + 1], 12, -389564586); c = ff(c, d, a, b, blks[i + 2], 17, 606105819); b = ff(b, c, d, a, blks[i + 3], 22, -1044525330);
    a = ff(a, b, c, d, blks[i + 4], 7, -176418897); d = ff(d, a, b, c, blks[i + 5], 12, 1200080426); c = ff(c, d, a, b, blks[i + 6], 17, -1473231341); b = ff(b, c, d, a, blks[i + 7], 22, -45705983);
    a = ff(a, b, c, d, blks[i + 8], 7, 1770035416); d = ff(d, a, b, c, blks[i + 9], 12, -1958414417); c = ff(c, d, a, b, blks[i + 10], 17, -42063); b = ff(b, c, d, a, blks[i + 11], 22, -1990404162);
    a = ff(a, b, c, d, blks[i + 12], 7, 1804603682); d = ff(d, a, b, c, blks[i + 13], 12, -40341101); c = ff(c, d, a, b, blks[i + 14], 17, -1502002290); b = ff(b, c, d, a, blks[i + 15], 22, 1236535329);
    a = gg(a, b, c, d, blks[i + 1], 5, -165796510); d = gg(d, a, b, c, blks[i + 6], 9, -1069501632); c = gg(c, d, a, b, blks[i + 11], 14, 643717713); b = gg(b, c, d, a, blks[i + 0], 20, -373897302);
    a = gg(a, b, c, d, blks[i + 5], 5, -701558691); d = gg(d, a, b, c, blks[i + 10], 9, 38016083); c = gg(c, d, a, b, blks[i + 15], 14, -660478335); b = gg(b, c, d, a, blks[i + 4], 20, -405537848);
    a = gg(a, b, c, d, blks[i + 9], 5, 568446438); d = gg(d, a, b, c, blks[i + 14], 9, -1019803690); c = gg(c, d, a, b, blks[i + 3], 14, -187363961); b = gg(b, c, d, a, blks[i + 8], 20, 1163531501);
    a = gg(a, b, c, d, blks[i + 13], 5, -1444681467); d = gg(d, a, b, c, blks[i + 2], 9, -51403784); c = gg(c, d, a, b, blks[i + 7], 14, 1735328473); b = gg(b, c, d, a, blks[i + 12], 20, -1926607734);
    a = hh(a, b, c, d, blks[i + 5], 4, -378558); d = hh(d, a, b, c, blks[i + 8], 11, -2022574463); c = hh(c, d, a, b, blks[i + 11], 16, 1839030562); b = hh(b, c, d, a, blks[i + 14], 23, -35309556);
    a = hh(a, b, c, d, blks[i + 1], 4, -1530992060); d = hh(d, a, b, c, blks[i + 4], 11, 1272893353); c = hh(c, d, a, b, blks[i + 7], 16, -155497632); b = hh(b, c, d, a, blks[i + 10], 23, -1094730640);
    a = hh(a, b, c, d, blks[i + 13], 4, 681279174); d = hh(d, a, b, c, blks[i + 0], 11, -358537222); c = hh(c, d, a, b, blks[i + 3], 16, -722521979); b = hh(b, c, d, a, blks[i + 6], 23, 76029189);
    a = hh(a, b, c, d, blks[i + 9], 4, -640364487); d = hh(d, a, b, c, blks[i + 12], 11, -421815835); c = hh(c, d, a, b, blks[i + 15], 16, 530742520); b = hh(b, c, d, a, blks[i + 2], 23, -995338651);
    a = ii(a, b, c, d, blks[i + 0], 6, -198630844); d = ii(d, a, b, c, blks[i + 7], 10, 1126891415); c = ii(c, d, a, b, blks[i + 14], 15, -1416354905); b = ii(b, c, d, a, blks[i + 5], 21, -57434055);
    a = ii(a, b, c, d, blks[i + 12], 6, 1700485571); d = ii(d, a, b, c, blks[i + 3], 10, -1894986606); c = ii(c, d, a, b, blks[i + 10], 15, -1051523); b = ii(b, c, d, a, blks[i + 1], 21, -2054922799);
    a = ii(a, b, c, d, blks[i + 8], 6, 1873313359); d = ii(d, a, b, c, blks[i + 15], 10, -30611744); c = ii(c, d, a, b, blks[i + 6], 15, -1560198380); b = ii(b, c, d, a, blks[i + 13], 21, 1309151649);
    a = ii(a, b, c, d, blks[i + 4], 6, -145523070); d = ii(d, a, b, c, blks[i + 11], 10, -1120210379); c = ii(c, d, a, b, blks[i + 2], 15, 718787259); b = ii(b, c, d, a, blks[i + 9], 21, -343485551);
    a = add(a, oa); b = add(b, ob); c = add(c, oc); d = add(d, od);
  }
  function rhex(n) {
    var s = "", j;
    for (j = 0; j < 4; j++) s += ("0" + ((n >> (j * 8)) & 255).toString(16)).slice(-2);
    return s;
  }
  return rhex(a) + rhex(b) + rhex(c) + rhex(d);
}

function pageRequest(method, url, body, contentType) {
  var src = "(function(){try{var x=new XMLHttpRequest();x.open(" +
    JSON.stringify(method) + "," + JSON.stringify(url) +
    ",false);x.withCredentials=true;" +
    (contentType ? "x.setRequestHeader('Content-Type'," + JSON.stringify(contentType) + ");" : "") +
    "x.send(" + (body == null ? "null" : JSON.stringify(body)) +
    ");return JSON.stringify({status:x.status,body:x.responseText});}catch(e){return JSON.stringify({error:String(e)});}})()";
  var raw = "";
  try { raw = unwrap(web.eval(src)); } catch (err) { return { error: String(err) }; }
  try { return JSON.parse(raw); } catch (err2) { return { error: String(raw).slice(0, 80) }; }
}

function mixinKey(img, sub) {
  var raw = String(img) + String(sub);
  var out = "";
  for (var i = 0; i < MIXIN.length; i++) out += raw.charAt(MIXIN[i]) || "";
  return out.slice(0, 32);
}

function signWbi(params, img, sub) {
  var signed = {};
  for (var key in params) signed[key] = params[key];
  signed.wts = String(Math.round(Date.now() / 1000));
  var names = [];
  for (var name in signed) names.push(name);
  names.sort();
  var parts = [];
  for (var i = 0; i < names.length; i++) {
    var value = String(signed[names[i]] == null ? "" : signed[names[i]]).replace(/[!'()*]/g, "");
    parts.push(encodeURIComponent(names[i]) + "=" + encodeURIComponent(value));
  }
  var query = parts.join("&");
  return query + "&w_rid=" + md5hex(query + mixinKey(img, sub));
}

function keyFromUrl(url) {
  var name = String(url || "").split("/").pop() || "";
  return name.replace(/\.[a-z0-9]+$/i, "");
}

function wbiKeys() {
  var now = Date.now();
  if (wbiCache && now - wbiCache.at < 30 * 60 * 1000) return { img: wbiCache.img, sub: wbiCache.sub };
  var nav = biliSend("/x/web-interface/nav");
  if (!nav.ok) return nav;
  var row = nav.data && nav.data.wbi_img ? nav.data.wbi_img : {};
  var img = keyFromUrl(row.img_url);
  var sub = keyFromUrl(row.sub_url);
  if (!img || !sub) return err("bilibili nav had no wbi key");
  wbiCache = { img: img, sub: sub, at: now };
  return { img: img, sub: sub };
}

function formBody(map) {
  var parts = [];
  for (var key in map) {
    parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(map[key] == null ? "" : map[key])));
  }
  return parts.join("&");
}

function queryOf(path) {
  var q = path.indexOf("?");
  var params = {};
  if (q < 0) return { pathname: path, params: params, raw: "" };
  var search = path.slice(q + 1).split("&");
  for (var i = 0; i < search.length; i++) {
    if (!search[i]) continue;
    var eq = search[i].indexOf("=");
    var key = eq < 0 ? search[i] : search[i].slice(0, eq);
    var value = eq < 0 ? "" : search[i].slice(eq + 1);
    try { key = decodeURIComponent(key); } catch (err) {}
    try { value = decodeURIComponent(value); } catch (err2) {}
    params[key] = value;
  }
  return { pathname: path.slice(0, q), params: params, raw: path.slice(q) };
}

function biliSend(path, init) {
  init = init || {};
  if (path.indexOf("/x/") !== 0) return err("unsupported bilibili path");
  if (init.auth && !web.loggedIn()) return err("未登录。还没有 B 站登录态。");
  if (!holdBrowsePage()) return err("浏览页还在打开");
  var session = readSession();
  var parsed = queryOf(path);
  var query = "";
  if (init.wbi) {
    var keys = wbiKeys();
    if (keys.ok === false) return keys;
    query = "?" + signWbi(parsed.params, keys.img, keys.sub);
  } else {
    query = parsed.raw;
  }
  var form = init.form ? copyMap(init.form) : null;
  if (form) {
    var csrf = session && session.csrf ? session.csrf : "";
    if (!csrf) return err("页面里没有 csrf");
    form.csrf = csrf;
    form.csrf_token = csrf;
  }
  var res = pageRequest(
    form ? "POST" : "GET",
    API + parsed.pathname + query,
    form ? formBody(form) : null,
    form ? "application/x-www-form-urlencoded" : ""
  );
  if (!res || res.error) return err(res && res.error ? res.error : "没有结果");
  var parsedBody = null;
  try { parsedBody = JSON.parse(res.body); } catch (parseErr) {
    return err("bilibili response was not json (" + res.status + ")");
  }
  if (!parsedBody || typeof parsedBody !== "object") return err("bilibili response was not an object");
  if (parsedBody.code !== 0) return err(String(parsedBody.message || parsedBody.code || "bilibili error"));
  return { ok: true, data: parsedBody.data };
}

function copyMap(map) {
  var out = {};
  for (var key in map) out[key] = map[key];
  return out;
}

function biliGet(path) {
  return biliSend(path);
}

function aidOf(bvid) {
  var got = biliGet("/x/web-interface/view?bvid=" + bvid);
  if (!got.ok) return got;
  var aid = Number(got.data && got.data.aid);
  if (!isFinite(aid) || aid <= 0) return err("video had no aid");
  return aid;
}

function videoReferer(bvid) {
  return "https://www.bilibili.com/video/" + bvid;
}

function biliHot(args) {
  var kind = args.kind == null || args.kind === "" ? "popular" : String(args.kind);
  if (kind !== "popular" && kind !== "ranking") return err("kind must be popular or ranking");
  var page = pageNum(args.page);
  if (!page) return err("page must be an integer from 1 to " + PAGE_CAP);
  var path = kind === "ranking"
    ? "/x/web-interface/ranking/v2?rid=0&type=all"
    : "/x/web-interface/popular?ps=" + LIST_CAP + "&pn=" + page;
  var got = biliGet(path);
  if (!got.ok) return got;
  var list = got.data && got.data.list;
  var items = [];
  if (list && list.length) {
    for (var i = 0; i < list.length && items.length < LIST_CAP; i++) {
      var card = cardFromArchive(list[i]);
      if (card) items.push(card);
    }
  }
  return ok({ kind: kind, page: page, items: items });
}

function biliSearch(args) {
  var keyword = String(args.keyword == null ? "" : args.keyword).replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "").slice(0, 80);
  if (!keyword) return err("keyword is empty");
  var page = pageNum(args.page);
  if (!page) return err("page must be an integer from 1 to " + PAGE_CAP);
  var got = biliSend("/x/web-interface/wbi/search/type?search_type=video&keyword=" + encodeURIComponent(keyword) + "&page=" + page, { wbi: true });
  if (!got.ok) return got;
  var result = got.data && got.data.result;
  var items = [];
  if (result && result.length) {
    for (var i = 0; i < result.length && items.length < LIST_CAP; i++) {
      var row = result[i];
      var bvid = parseBvid(row.bvid);
      var title = stripHtml(row.title);
      if (!bvid || !title) continue;
      items.push({
        bvid: bvid,
        title: title,
        author: String(row.author || ""),
        duration: String(row.duration || ""),
        views: Number(row.play || 0),
        description: stripHtml(row.description).slice(0, 120)
      });
    }
  }
  return ok({ keyword: keyword, page: page, items: items });
}

function biliVideo(args) {
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var got = biliGet("/x/web-interface/view?bvid=" + bvid);
  if (!got.ok) return got;
  var row = got.data;
  if (!row) return err("video response was empty");
  var stat = row.stat || {};
  var pages = [];
  if (row.pages && row.pages.length) {
    for (var i = 0; i < row.pages.length && i < 12; i++) {
      pages.push({
        index: i + 1,
        part: String(row.pages[i].part || ""),
        duration: clock(row.pages[i].duration)
      });
    }
  }
  var out = {
    bvid: bvid,
    title: stripHtml(row.title),
    desc: stripHtml(row.desc).slice(0, 400),
    duration: clock(row.duration),
    tname: String(row.tname_v2 || row.tname || ""),
    owner: String(row.owner && row.owner.name || ""),
    owner_mid: Number(row.owner && row.owner.mid || 0),
    stat: {
      view: Number(stat.view || 0),
      like: Number(stat.like || 0),
      coin: Number(stat.coin || 0),
      favorite: Number(stat.favorite || 0),
      reply: Number(stat.reply || 0),
      danmaku: Number(stat.danmaku || 0)
    }
  };
  if (pages.length > 1) out.pages = pages;
  return ok(out);
}

function slimReplies(payload) {
  if (!payload || typeof payload !== "object") return null;
  var next = Number(payload.cursor && payload.cursor.next || 0);
  var replies = [];
  var list = payload.replies;
  if (list && list.length) {
    for (var i = 0; i < list.length; i++) {
      var row = list[i];
      if (!row) continue;
      var message = stripHtml(row.content && row.content.message);
      if (!message) continue;
      replies.push({
        rpid: Number(row.rpid || 0),
        uname: String(row.member && row.member.uname || ""),
        message: message.slice(0, 180),
        like: Number(row.like || 0)
      });
    }
  }
  return { next: isFinite(next) ? next : 0, end: !!(payload.cursor && payload.cursor.is_end), replies: replies };
}

function biliComments(args) {
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var sort = args.sort == null || args.sort === "" ? "hot" : String(args.sort);
  if (sort !== "hot" && sort !== "new") return err("sort must be hot or new");
  var cursor = args.cursor == null || args.cursor === "" ? 0 : Number(args.cursor);
  if (cursor !== Math.floor(cursor) || cursor < 0) return err("cursor must be a non-negative integer");
  var video = biliGet("/x/web-interface/view?bvid=" + bvid);
  if (!video.ok) return video;
  var aid = Number(video.data && video.data.aid);
  if (!isFinite(aid) || aid <= 0) return err("video had no aid");
  var mode = sort === "new" ? 2 : 3;
  var got = biliGet("/x/v2/reply/main?type=1&oid=" + aid + "&mode=" + mode + "&next=" + cursor + "&ps=" + LIST_CAP);
  if (!got.ok) return got;
  var slim = slimReplies(got.data);
  if (!slim) return err("comment response was empty");
  slim.bvid = bvid;
  slim.sort = sort;
  return ok(slim);
}

function slimConclusion(data) {
  if (!data || data.code !== 0 || !data.model_result) return null;
  var summary = stripHtml(data.model_result.summary).slice(0, 800);
  var outline = [];
  var parts = data.model_result.outline;
  if (parts && parts.length) {
    for (var i = 0; i < parts.length && outline.length < 8; i++) {
      var item = parts[i];
      if (!item) continue;
      var points = [];
      var lines = item.part_outline;
      if (lines && lines.length) {
        for (var j = 0; j < lines.length && points.length < 4; j++) {
          var content = stripHtml(lines[j] && lines[j].content).slice(0, 160);
          if (!content) continue;
          points.push({ timestamp: Number(lines[j].timestamp || 0), content: content });
        }
      }
      var title = stripHtml(item.title).slice(0, 160);
      if (!title && !points.length) continue;
      outline.push({ timestamp: Number(item.timestamp || 0), title: title, points: points });
    }
  }
  if (!summary && !outline.length) return null;
  return { summary: summary, outline: outline };
}

function pickZhSubtitle(subtitles) {
  if (!subtitles || !subtitles.length) return null;
  var best = null;
  var bestRank = 9;
  for (var i = 0; i < subtitles.length; i++) {
    var row = subtitles[i];
    if (!row) continue;
    var lan = String(row.lan || "");
    var url = String(row.subtitle_url || "");
    var rank = 9;
    if (lan === "zh-Hans") rank = 0;
    else if (lan === "zh-CN") rank = 1;
    else if (lan === "ai-zh") rank = 2;
    else if (lan.indexOf("zh") === 0) rank = 3;
    if (!url || rank === 9 || rank >= bestRank) continue;
    best = { lan: lan, url: url };
    bestRank = rank;
  }
  return best;
}

function subtitleFileUrl(url) {
  if (url.indexOf("https://") === 0 || url.indexOf("http://") === 0) return url;
  if (url.indexOf("//") === 0) return "https:" + url;
  return "";
}

function slimCues(payload, fromSec) {
  var cues = payload && payload.body;
  var lines = [];
  var chars = 0;
  if (!cues || !cues.length) return { lines: lines, next_from: null };
  for (var i = 0; i < cues.length; i++) {
    var row = cues[i];
    if (!row) continue;
    var from = Number(row.from || 0);
    var to = Number(row.to || from);
    if (!(to > fromSec)) continue;
    var content = stripHtml(row.content).slice(0, 200);
    if (!content) continue;
    if (lines.length && chars >= TEXT_CAP) return { lines: lines, next_from: from };
    lines.push({ from: from, content: content });
    chars += content.length;
  }
  return { lines: lines, next_from: null };
}

function biliRead(args) {
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var fromSec = args.from == null || args.from === "" ? 0 : Number(args.from);
  if (!isFinite(fromSec) || fromSec < 0) return err("from must be a non-negative number of seconds");
  var video = biliGet("/x/web-interface/view?bvid=" + bvid);
  if (!video.ok) return video;
  var row = video.data || {};
  var aid = Number(row.aid || 0);
  var cid = Number(row.cid || 0);
  var mid = Number(row.owner && row.owner.mid || 0);
  var title = stripHtml(row.title);
  var desc = stripHtml(row.desc).slice(0, 400);
  if (!isFinite(aid) || aid <= 0 || !isFinite(cid) || cid <= 0) return err("video had no cid");
  if (fromSec === 0) {
    var conclusion = biliSend("/x/web-interface/view/conclusion/get?bvid=" + bvid + "&cid=" + cid + "&up_mid=" + mid, { wbi: true });
    if (conclusion.ok) {
      var slim = slimConclusion(conclusion.data);
      if (slim) {
        slim.bvid = bvid;
        slim.title = title;
        slim.source = "summary";
        return ok(slim);
      }
    }
  }
  var player = biliSend("/x/player/wbi/v2?aid=" + aid + "&cid=" + cid, { wbi: true });
  if (!player.ok) return player;
  var track = pickZhSubtitle(player.data && player.data.subtitle && player.data.subtitle.subtitles);
  var fileUrl = track ? subtitleFileUrl(track.url) : "";
  if (!track || !fileUrl || fileUrl.indexOf("https://") !== 0) {
    return ok({ bvid: bvid, title: title, source: "none", desc: desc });
  }
  var res = http.request({
    url: fileUrl,
    method: "GET",
    headers: { "User-Agent": UA, Referer: "https://www.bilibili.com" },
    timeoutMs: 20000
  });
  if (!res || res.error) return err(res && res.error ? res.error : "subtitle error");
  var payload = null;
  try { payload = JSON.parse(res.body); } catch (e) { return err("subtitle error"); }
  var cues = slimCues(payload, fromSec);
  cues.bvid = bvid;
  cues.title = title;
  cues.source = "subtitle";
  cues.lan = track.lan;
  return ok(cues);
}

function biliRelated(args) {
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var got = biliGet("/x/web-interface/archive/related?bvid=" + bvid);
  if (!got.ok) return got;
  var list = got.data;
  var items = [];
  if (list && list.length) {
    for (var i = 0; i < list.length && items.length < LIST_CAP; i++) {
      var card = cardFromArchive(list[i]);
      if (card) items.push(card);
    }
  }
  return ok({ bvid: bvid, items: items });
}

function biliMe() {
  var got = biliGet("/x/web-interface/nav");
  if (!got.ok) return got;
  var row = got.data || {};
  return ok({
    logged_in: !!row.isLogin,
    uname: String(row.uname || ""),
    mid: Number(row.mid || 0),
    level: Number(row.level_info && row.level_info.current_level || 0),
    coins: Number(row.money || 0)
  });
}

function biliFeed(args) {
  var signed = needLogin();
  if (signed) return signed;
  var offset = String(args.offset == null ? "" : args.offset).replace(/^\s+|\s+$/g, "").slice(0, 200);
  var path = "/x/polymer/web-dynamic/v1/feed/all?type=all&features=itemOpusStyle" + (offset ? "&offset=" + encodeURIComponent(offset) : "");
  var got = biliSend(path, { auth: true });
  if (!got.ok) return got;
  var data = got.data || {};
  var items = [];
  if (data.items && data.items.length) {
    for (var i = 0; i < data.items.length && items.length < LIST_CAP; i++) {
      var row = data.items[i] || {};
      var modules = row.modules || {};
      var dynamic = modules.module_dynamic || {};
      var archive = dynamic.major && dynamic.major.archive || {};
      var bvid = parseBvid(archive.bvid);
      var text = stripHtml(dynamic.desc && dynamic.desc.text).slice(0, 180);
      var title = stripHtml(archive.title).slice(0, 120);
      if (!text && !title) continue;
      items.push({
        author: stripHtml(modules.module_author && modules.module_author.name),
        text: text,
        bvid: bvid,
        title: title
      });
    }
  }
  return ok({ offset: String(data.offset || ""), items: items });
}

function biliHistory(args) {
  var signed = needLogin();
  if (signed) return signed;
  var max = args.max == null || args.max === "" ? 0 : Number(args.max);
  var viewAt = args.view_at == null || args.view_at === "" ? 0 : Number(args.view_at);
  if (max !== Math.floor(max) || max < 0 || viewAt !== Math.floor(viewAt) || viewAt < 0) {
    return err("max and view_at must be non-negative integers");
  }
  var got = biliSend("/x/web-interface/history/cursor?ps=" + LIST_CAP + "&business=archive&max=" + max + "&view_at=" + viewAt, { auth: true });
  if (!got.ok) return got;
  var data = got.data || {};
  var items = [];
  if (data.list && data.list.length) {
    for (var i = 0; i < data.list.length; i++) {
      var row = data.list[i] || {};
      var bvid = parseBvid(row.history && row.history.bvid);
      if (!bvid) continue;
      items.push({
        bvid: bvid,
        title: stripHtml(row.title).slice(0, 120),
        author: stripHtml(row.author_name),
        progress: Number(row.progress || 0)
      });
    }
  }
  return ok({
    max: Number(data.cursor && data.cursor.max || 0),
    view_at: Number(data.cursor && data.cursor.view_at || 0),
    items: items
  });
}

function defaultFolder() {
  var session = readSession();
  if (!session) return err("未登录。还没有 B 站登录态。");
  var got = biliSend("/x/v3/fav/folder/created/list-all?up_mid=" + encodeURIComponent(session.mid), { auth: true });
  if (!got.ok) return got;
  var list = got.data && got.data.list || [];
  var id = 0;
  for (var i = 0; i < list.length; i++) {
    if (stripHtml(list[i].title) === "默认收藏夹") {
      id = Number(list[i].id || 0);
      break;
    }
  }
  if (!id && list.length) id = Number(list[0].id || 0);
  if (!id) return err("这个帐号没有收藏夹");
  return id;
}

function biliFavs(args) {
  var session = readSession();
  if (!session) return err("未登录。还没有 B 站登录态。");
  if (args.media_id == null || args.media_id === "") {
    var got = biliSend("/x/v3/fav/folder/created/list-all?up_mid=" + encodeURIComponent(session.mid), { auth: true });
    if (!got.ok) return got;
    var list = got.data && got.data.list;
    var folders = [];
    if (list && list.length) {
      for (var i = 0; i < list.length && folders.length < 20; i++) {
        var folder = {
          media_id: Number(list[i].id || 0),
          title: stripHtml(list[i].title),
          count: Number(list[i].media_count || 0)
        };
        if (folder.media_id > 0) folders.push(folder);
      }
    }
    return ok({ folders: folders });
  }
  var mediaId = Number(args.media_id);
  var page = args.page == null || args.page === "" ? 1 : Number(args.page);
  if (mediaId !== Math.floor(mediaId) || mediaId <= 0 || page !== Math.floor(page) || page < 1 || page > 20) {
    return err("media_id and page must be positive integers");
  }
  var inner = biliSend("/x/v3/fav/resource/list?media_id=" + mediaId + "&pn=" + page + "&ps=" + LIST_CAP + "&platform=web", { auth: true });
  if (!inner.ok) return inner;
  var medias = inner.data && inner.data.medias;
  var items = [];
  if (medias && medias.length) {
    for (var j = 0; j < medias.length; j++) {
      var bvid = parseBvid(medias[j].bvid);
      if (!bvid) continue;
      items.push({
        bvid: bvid,
        title: stripHtml(medias[j].title).slice(0, 120),
        author: stripHtml(medias[j].upper && medias[j].upper.name)
      });
    }
  }
  return ok({ media_id: mediaId, page: page, items: items });
}

function biliSpace(args) {
  var mid = Number(args.mid);
  var page = args.page == null || args.page === "" ? 1 : Number(args.page);
  if (mid !== Math.floor(mid) || mid <= 0 || page !== Math.floor(page) || page < 1 || page > 20) {
    return err("mid and page must be positive integers");
  }
  var got = biliSend("/x/space/wbi/arc/search?mid=" + mid + "&pn=" + page + "&ps=" + LIST_CAP, { wbi: true });
  if (!got.ok) return got;
  var vlist = got.data && got.data.list && got.data.list.vlist;
  var items = [];
  if (vlist && vlist.length) {
    for (var i = 0; i < vlist.length && items.length < LIST_CAP; i++) {
      var bvid = parseBvid(vlist[i].bvid);
      if (!bvid) continue;
      items.push({
        bvid: bvid,
        title: stripHtml(vlist[i].title).slice(0, 120),
        author: stripHtml(vlist[i].author),
        views: Number(vlist[i].play || 0),
        duration: String(vlist[i].length || "")
      });
    }
  }
  return ok({ mid: mid, page: page, items: items });
}

function biliLike(args) {
  var signed = needLogin();
  if (signed) return signed;
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var action = args.action == null || args.action === "" ? "like" : String(args.action);
  if (action !== "like" && action !== "unlike") return err("action must be like or unlike");
  var aid = aidOf(bvid);
  if (typeof aid !== "number") return aid;
  var got = biliSend("/x/web-interface/archive/like", {
    form: { aid: String(aid), like: action === "like" ? "1" : "2" },
    referer: videoReferer(bvid),
    auth: true
  });
  if (!got.ok) return got;
  return ok({ bvid: bvid, action: action });
}

function biliCoin(args) {
  var count = Number(args.count);
  if (count !== 1 && count !== 2) return err("count must be 1 or 2");
  var signed = needLogin();
  if (signed) return signed;
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var aid = aidOf(bvid);
  if (typeof aid !== "number") return aid;
  var got = biliSend("/x/web-interface/coin/add", {
    form: {
      aid: String(aid),
      multiply: String(count),
      select_like: args.also_like === true ? "1" : "0"
    },
    referer: videoReferer(bvid),
    auth: true
  });
  if (!got.ok) return got;
  return ok({ bvid: bvid, count: count });
}

function biliFav(args) {
  var signed = needLogin();
  if (signed) return signed;
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var action = args.action == null || args.action === "" ? "add" : String(args.action);
  if (action !== "add" && action !== "remove") return err("action must be add or remove");
  var mediaId = args.media_id == null || args.media_id === "" ? 0 : Number(args.media_id);
  if (mediaId !== Math.floor(mediaId) || mediaId < 0) return err("media_id must be a positive integer");
  if (mediaId === 0) {
    var folder = defaultFolder();
    if (typeof folder !== "number") return folder;
    mediaId = folder;
  }
  var aid = aidOf(bvid);
  if (typeof aid !== "number") return aid;
  var got = biliSend("/x/v3/fav/resource/deal", {
    form: {
      rid: String(aid),
      type: "2",
      add_media_ids: action === "add" ? String(mediaId) : "",
      del_media_ids: action === "remove" ? String(mediaId) : ""
    },
    referer: videoReferer(bvid),
    auth: true
  });
  if (!got.ok) return got;
  return ok({ bvid: bvid, action: action, media_id: mediaId });
}

function biliFollow(args) {
  var signed = needLogin();
  if (signed) return signed;
  var mid = Number(args.mid);
  if (mid !== Math.floor(mid) || mid <= 0) return err("mid must be a positive integer");
  var action = args.action == null || args.action === "" ? "follow" : String(args.action);
  if (action !== "follow" && action !== "unfollow") return err("action must be follow or unfollow");
  var got = biliSend("/x/relation/modify", {
    form: { fid: String(mid), act: action === "follow" ? "1" : "2", re_src: "11" },
    auth: true
  });
  if (!got.ok) return got;
  return ok({ mid: mid, action: action });
}

function biliComment(args) {
  var text = String(args.text == null ? "" : args.text).replace(/^\s+|\s+$/g, "").slice(0, 300);
  if (!text) return err("text is empty");
  var signed = needLogin();
  if (signed) return signed;
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var replyTo = args.reply_to == null || args.reply_to === "" ? 0 : Number(args.reply_to);
  if (replyTo !== Math.floor(replyTo) || replyTo < 0) return err("reply_to must be a non-negative integer");
  var aid = aidOf(bvid);
  if (typeof aid !== "number") return aid;
  var form = { oid: String(aid), type: "1", message: text, plat: "1" };
  if (replyTo > 0) {
    form.root = String(replyTo);
    form.parent = String(replyTo);
  }
  var got = biliSend("/x/v2/reply/add", { form: form, referer: videoReferer(bvid), auth: true });
  if (!got.ok) return got;
  return ok({ bvid: bvid, rpid: Number(got.data && got.data.rpid || 0) });
}

function biliToview(args) {
  var signed = needLogin();
  if (signed) return signed;
  var bvid = parseBvid(args.bvid);
  if (!bvid) return err("bvid is required, like BV1xx411c7mD");
  var aid = aidOf(bvid);
  if (typeof aid !== "number") return aid;
  var got = biliSend("/x/v2/history/toview/add", {
    form: { aid: String(aid) },
    referer: videoReferer(bvid),
    auth: true
  });
  if (!got.ok) return got;
  return ok({ bvid: bvid, action: "toview" });
}
