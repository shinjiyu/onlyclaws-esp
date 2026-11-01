import { Agent } from "@earendil-works/pi-agent-core";
import { Type, createModels, createProvider, envApiKeyAuth } from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { anthropicProvider } from "@earendil-works/pi-ai/providers/anthropic";
import { deepseekProvider } from "@earendil-works/pi-ai/providers/deepseek";
import { googleProvider } from "@earendil-works/pi-ai/providers/google";
import { groqProvider } from "@earendil-works/pi-ai/providers/groq";
import { minimaxProvider } from "@earendil-works/pi-ai/providers/minimax";
import { minimaxCnProvider } from "@earendil-works/pi-ai/providers/minimax-cn";
import { moonshotaiProvider } from "@earendil-works/pi-ai/providers/moonshotai";
import { moonshotaiCnProvider } from "@earendil-works/pi-ai/providers/moonshotai-cn";
import { openaiProvider } from "@earendil-works/pi-ai/providers/openai";
import { openrouterProvider } from "@earendil-works/pi-ai/providers/openrouter";
import { xaiProvider } from "@earendil-works/pi-ai/providers/xai";
import { zaiProvider } from "@earendil-works/pi-ai/providers/zai";
import { zaiCodingCnProvider } from "@earendil-works/pi-ai/providers/zai-coding-cn";
import { installPolyfill } from "./polyfill.js";

const SYSTEM = `你在一台安卓手机上，是 OnlyClaws 的本地 agent。

平时就正常聊天：用中文直接回答。不要因为用户说了一句话就去改屏幕、装脚本或画界面。
只有用户明确要求做界面、改界面、装一个小程序、画 UI、换壁纸这类事时，才调用 apps_install。
不要预装任何应用。没有在跑的界面时，保持空白。

壁纸这个词只对应 wallpaper。用户说壁纸、桌面背景、换壁纸、星空壁纸、去掉壁纸时，脚本里只能调用 wallpaper.load 或 wallpaper.clear。禁止用 gfx、screen、onFrame 画壁纸，禁止用浮层铺满来假装壁纸。
- 纯色：wallpaper.load({ color: 0x05060e, text, textColor, size, x, y })。color 是 RGB 或 ARGB 数字。
- 会动的预设只有一个：wallpaper.load({ scene: "crash" })。
- 去掉：wallpaper.clear()。
星空、银河、夜空也走 wallpaper.load({ color: 0x05060e })。没有逐颗画星星的壁纸接口。做不到的部分在聊天里说明，不要改用 gfx.circle。load 只换预设；若桌面还不是 OnlyClaws 壁纸，告诉用户到应用里点一次「设为动态壁纸」。

apps_install 会把一段 JavaScript 装进本机脚本容器。脚本环境是 V8，host API 是同步的，没有 setTimeout。
钩子必须写成 function 声明：onStart() / onStop() / onFrame(dt) / onAction(e) / onPointer(e) / onSpeech(e) / onDone()。
生成脚本可以上网。http.request({ url, method, headers, body, timeoutMs }) 和 fetch(url, init) 都是同步的，只能 https。http.request 返回 { status, body, error, headers }。fetch 另外有 ok、text()、json()。没有密钥，公开接口直接调。不要说脚本没有网络。
套接字只能主动连出去：socket.open({ host, port, timeoutMs }) → { id, error }。socket.send(id, { text } 或 { b64 })。socket.recv(id, { maxBytes, timeoutMs }) → { text, b64, n, eof, error }。socket.close(id)。不能监听端口。
SSH：ssh.exec({ host, port, user, password 或 privateKey, command, timeoutMs }) → { code, stdout, stderr, error, fingerprint }。跑完一条命令就断开。第一次记住主机指纹，变了就拒绝；用户确认新指纹时把 fingerprint 传进去。密码和私钥不要写到界面或日志上。不要在 onFrame 里调用 socket 或 ssh。
另外可用：screen、gfx、ui、tts、asr、llm、wallpaper、oca.log。没有 a2ui。
没有 keys、web、desk。做不到的事先在聊天里说。

浮层（盖住其它 App，要系统「显示在其他应用上层」）：
- ui.w / ui.h / ui.safe：逻辑像素。
- gfx.clear(color)、gfx.rect(x,y,w,h,color)、gfx.line、gfx.circle(x,y,r,color)、gfx.text(x,y,text,color)、gfx.text_width(text)。
- 颜色是 ARGB 数字；6 位当不透明。clear(0) 清空。每帧先 clear 再画。
- 写 function onFrame(dt) 才会每帧刷新。点在较小的图形上会 onPointer({ action, x, y })，action 是 down/move/up/cancel。铺满屏幕的 clear、横条、大圆只是画面，不吃触摸。gfx 不是壁纸，用户提到壁纸时不要用这段。

语音：asr.warm()；asr.ready / asr.hasModel / asr.listening / asr.deaf。按住角色 asr.start()，松开 asr.stop()。只在按住说话时 start，不要在拖动时 start。识别走 onSpeech({ text, partial, error? })。partial 为 false 才是一句完整的话。聊天球的「说」会抢走麦克风，这时 asr.start 失败，onSpeech 带 error。

模型决策：llm.ready / llm.provider / llm.model。llm.chat({ messages:[{role,content}], system? }) 同步返回 { text, error, provider, model }。key 由宿主代发，脚本拿不到。只支持 OpenAI 兼容后端。不要在 onFrame 里调用。tts.say(text) 朗读，tts.speaking 为真；结束 onDone()。朗读时宿主会关掉脚本麦克风，播完短时间 asr.deaf，避免它听见自己。不要在 onDone 里立刻 asr.start。

界面这个词只对应 screen。用户要界面、UI、按钮、表单或好看的画面时，用 screen.show(html) 装进应用主界面。一段内嵌 HTML，可以用 SVG 和 CSS，包括立体按钮。禁止 a2ui。不要用 gfx 画主界面。
screen.show(html) 换掉整页。screen.clear() 清掉。可点的地方写 data-action="动作名"，输入框写 data-field="字段名"。点下去调用 onAction({ action, context })，context 是当时各 data-field 的值，按钮上的 data-value 放进 context.value。
页面不能打开链接，也不能加载网络图片或脚本，SVG 和样式都写在这段 HTML 里。要换界面就再调用一次 screen.show。
要趴在桌面上的角色、桌宠，用 gfx + onFrame + asr + llm + tts，不要用 screen 盖住桌面。

装上失败时，工具会返回报错、出错的那一行和试装日志。根据这些自己改脚本再装。不要用 try/catch 把错误吞掉。不要让用户重启 App，也不要说宿主坏了。`;

function factories() {
  return [
    deepseekProvider,
    openaiProvider,
    anthropicProvider,
    googleProvider,
    openrouterProvider,
    moonshotaiProvider,
    moonshotaiCnProvider,
    zaiProvider,
    zaiCodingCnProvider,
    minimaxProvider,
    minimaxCnProvider,
    groqProvider,
    xaiProvider,
  ];
}

function catalog() {
  return factories().map((fn) => {
    const p = fn();
    const models = (p.getModels?.() ?? []).map((m) => ({
      id: m.id,
      name: m.name,
      api: m.api,
    }));
    return { id: p.id, name: p.name, models };
  });
}

function tools(host) {
  return [
    {
      name: "apps_install",
      label: "装脚本",
      description:
        "把一段完整 JavaScript 装进手机脚本容器并立刻运行。只在用户明确要求做界面或改界面时用。失败时返回报错和日志。",
      parameters: Type.Object({
        title: Type.String({ description: "不超过 12 个字的名字" }),
        source: Type.String({ description: "完整脚本，必须有 function onStart" }),
      }),
      execute: async (_id, params) => {
        const text = host.installApp(params.title || "", params.source || "");
        return { content: [{ type: "text", text }] };
      },
    },
    {
      name: "apps_read",
      label: "读脚本",
      description: "读取手机上正在跑的脚本。没有则返回空。",
      parameters: Type.Object({}),
      execute: async () => {
        const text = host.readApp() || "（没有正在跑的脚本）";
        return { content: [{ type: "text", text }] };
      },
    },
    {
      name: "apps_unload",
      label: "卸脚本",
      description: "卸掉当前脚本，屏幕回到空容器。",
      parameters: Type.Object({}),
      execute: async () => {
        const text = host.unloadApp();
        return { content: [{ type: "text", text }] };
      },
    },
    {
      name: "apps_logs",
      label: "读日志",
      description: "读取脚本容器最近的日志，用来查装上失败的原因。",
      parameters: Type.Object({}),
      execute: async () => {
        const text = host.readLogs() || "（没有日志）";
        return { content: [{ type: "text", text }] };
      },
    },
  ];
}

function addCustom(models, custom) {
  if (!custom || !custom.baseUrl || !custom.model) return;
  const id = custom.id || "custom";
  const api = custom.api || "openai-completions";
  models.setProvider(
    createProvider({
      id,
      name: custom.name || "自定义",
      baseUrl: custom.baseUrl,
      auth: { apiKey: envApiKeyAuth("Custom", []) },
      models: [
        {
          id: custom.model,
          name: custom.model,
          api,
          provider: id,
          baseUrl: custom.baseUrl,
          reasoning: false,
          input: ["text"],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: Number(custom.contextWindow) || 128000,
          maxTokens: Number(custom.maxTokens) || 8192,
        },
      ],
      api: openAICompletionsApi(),
    }),
  );
}

function pickModel(models, settings) {
  const provider = settings.provider || "deepseek";
  const id = settings.model || "deepseek-flash";
  const found = models.getModel(provider, id);
  if (found) return found;
  const first = models.getModels(provider)[0] || models.getModels()[0];
  if (!first) throw new Error("没有可用模型，先在设置里配一家后端");
  return first;
}

let agent = null;

function start(host, settingsJson) {
  installPolyfill(host);
  const settings = JSON.parse(settingsJson || "{}");
  const models = createModels();
  for (const fn of factories()) models.setProvider(fn());
  addCustom(models, settings.custom);
  const model = pickModel(models, settings);
  agent = new Agent({
    initialState: {
      systemPrompt: SYSTEM,
      model,
      tools: tools(host),
    },
    streamFn: (...args) => {
      try {
        return models.streamSimple(...args);
      } catch (e) {
        OcaHost.log("stream " + (e && e.stack ? e.stack : e));
        throw e;
      }
    },
    onPayload: (params) => {
      try {
        OcaHost.log("payload " + params.model + " msgs=" + (params.messages ? params.messages.length : 0));
      } catch (e) {
        OcaHost.log("payload " + e);
      }
      return params;
    },
    getApiKey: (provider) => host.getKey(provider) || undefined,
    identity: { attribution: { name: "OnlyClaws", url: "https://onlyclaws.app" } },
  });
  agent.subscribe((event) => {
    try {
      if (event.type !== "message_update") host.log(event.type);
      host.event(event.type, slim(event));
    } catch (e) {
      host.log("event " + event.type + "：" + (e && e.message ? e.message : e));
    }
  });
  return JSON.stringify({
    provider: model.provider,
    model: model.id,
    name: model.name,
    catalog: catalog(),
  });
}

async function prompt(text) {
  if (!agent) throw new Error("agent 还没启动");
  try {
    OcaHost.log("prompt " + String(text || "").slice(0, 80));
    await agent.prompt(String(text || ""));
    OcaHost.log("prompt done");
  } catch (e) {
    hostEvent("error", { text: String(e && e.message ? e.message : e) });
  }
}

function hostEvent(type, payload) {
  try {
    OcaHost.event(type, JSON.stringify(payload));
  } catch (e) {
    OcaHost.log("host.event：" + e);
  }
}

function textOf(message) {
  if (!message) return "";
  if (typeof message.content === "string") return message.content;
  const parts = message.content;
  if (!Array.isArray(parts)) return "";
  return parts.map((b) => (b && b.type === "text" ? b.text : "")).join("");
}

function slim(event) {
  const out = { type: event.type };
  if (event.message) {
    out.role = event.message.role;
    out.text = textOf(event.message);
    if (event.message.errorMessage) out.error = event.message.errorMessage;
    if (event.message.stopReason) out.stop = event.message.stopReason;
  }
  const ev = event.assistantMessageEvent;
  if (ev) {
    out.event = ev.type;
    if (ev.type === "text_delta" && ev.delta) out.delta = ev.delta;
  }
  if (event.toolName) out.toolName = event.toolName;
  if (event.errorMessage) out.error = event.errorMessage;
  return JSON.stringify(out);
}

function abort() {
  agent?.abort();
}

globalThis.OcaAgent = { start, prompt, abort, catalog };
