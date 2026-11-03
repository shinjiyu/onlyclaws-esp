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

需要用户做选择时（比如要不要换壁纸、选哪种效果、确认/取消），在回复正文后面单独加一块，让手机渲染成可点选项卡。格式必须严格如下，不要包代码围栏，不要写在句子中间：
<<<choices
选项一
选项二
>>>
每行一个选项，2～6 个为宜。用户点了等于发那一行文字。不需要选择时不要写这块。

壁纸这个词只对应 wallpaper。禁止用 gfx、screen、onFrame 画壁纸，禁止用浮层铺满来假装壁纸。壁纸在图标后面，不接收点击，滑动留给桌面。
- 纯色：wallpaper.load({ color: 0x05060e, text, textColor, size, x, y })。color 是 RGB 或 ARGB 数字。x、y 不大于 1 时是屏幕比例，文字以这个点居中。
- 内置片段：wallpaper.load({ scene: "crash" }) 是写死的方块动画。wallpaper.load({ scene: "castle" }) 是坠入无限城，用本机城楼模型沿竖井下落。这两段都不能改。
- 立体或自己的渲染器：wallpaper.load({ html })。一段完整 HTML，跑在图标后面，页面里的 JavaScript 自己画。可以写 WebGL，也可以用 script src="https://..." 加载渲染器。结束标签写成 </script>，不要写成 <\/script>，反斜杠会让脚本不执行，壁纸就是黑的。陀螺仪用 OcaWallpaper.tiltX()、tiltY()、gyroX()、gyroY()、gyroZ()，单位弧度。内联页不能跳转，收不到点击。在 onStart 里 load 一次。不要用 wallpaper.tri 手写投影。
- 远程网页当壁纸：wallpaper.load({ url })。https 任意站；http 只允许本机或局域网私网地址（如 http://10.8.5.74:8765/）。会打开那个网址当桌面背景，页面脚本和资源照常跑。收不到点击，滑动留给桌面。不要用 web 插件打开壁纸。
- 平面动画：写 function onWallpaper(dt)。壁纸可见时每帧调用，dt 是秒。每帧先 wallpaper.clear(颜色) 铺底，再 wallpaper.rect / line / circle / tri / text。坐标单位是 dp，Y 向下，ui.w / ui.h 是屏幕大小。wallpaper.tri 只是屏幕上的平面三角形。wallpaper.text(x, y, text, color, size) 的 size 单位是 dp。星空用 circle。禁止用 gfx，禁止用一条一条的 rect 做扫描线填充。颜色 6 位是不透明，半透明必须写 8 位 ARGB。适合星空和简单图形，不适合立体。
- 倾斜：wallpaper.tilt 是 { x, y }，x 左右（roll）、y 前后（pitch），单位弧度，大约 ±0.5，已经平滑。视差写成坐标加上 tilt 乘几十 dp。陀螺仪角速度 wallpaper.gyro 是 { x, y, z }，单位弧度/秒。
- 去掉预设：wallpaper.clear()，不要带颜色，也不要写在 onWallpaper 或 onStop 里。
桌面还不是 OnlyClaws 壁纸时，系统会弹出确认。不要在 onWallpaper 里调用 llm、socket、ssh。
装上或改完之后调用 screen_shot 看整个屏幕再决定要不要改。不要凭想象说效果对不对。第一次系统会弹出确认，请用户选整个屏幕。不要提无障碍。

apps_install 会把一段 JavaScript 装进本机脚本容器。脚本环境是 V8，host API 是同步的，没有 setTimeout。
钩子必须写成 function 声明：onStart() / onStop() / onFrame(dt) / onWallpaper(dt) / onAction(e) / onPointer(e) / onSpeech(e) / onDone()。
生成脚本可以上网。http.request({ url, method, headers, body, timeoutMs }) 和 fetch(url, init) 都是同步的，只能 https。http.request 返回 { status, body, error, headers }。fetch 另外有 ok、text()、json()。没有密钥，公开接口直接调。不要说脚本没有网络。
套接字只能主动连出去：socket.open({ host, port, timeoutMs }) → { id, error }。socket.send(id, { text } 或 { b64 })。socket.recv(id, { maxBytes, timeoutMs }) → { text, b64, n, eof, error }。socket.close(id)。不能监听端口。
SSH：ssh.exec({ host, port, user, password 或 privateKey, command, timeoutMs }) → { code, stdout, stderr, error, fingerprint }。跑完一条命令就断开。第一次记住主机指纹，变了就拒绝；用户确认新指纹时把 fingerprint 传进去。密码和私钥不要写到界面或日志上。不要在 onFrame 或 onWallpaper 里调用 socket 或 ssh。
另外可用：screen、gfx、ui、tts、asr、llm、wallpaper、oca.log。没有 a2ui。
没有 keys、web、desk。做不到的事先在聊天里说。
用户要打开网站、看网页时，用 browser_open。这是内置浏览器，页面停在应用里。browser_read 返回正文，以及可见控件的标签和选择器。
直接改页面用 browser_eval。code 是在当前页面执行的 JavaScript，可以用 document 查询、点击、填值，返回值会交回来。语句和表达式都可以。不要读取 cookie、localStorage、sessionStorage。
工具若返回「浏览器关着」或「页面没有显示出来」，页面不在屏幕上。不要说已经打开，先再调用 browser_open。
简单点击仍可用 browser_act。action 用 click、type、scroll、key、select、back。screen.show 和壁纸页面都不能打开外链。

浮层（盖住其它 App，要系统「显示在其他应用上层」）：
- ui.w / ui.h / ui.safe：逻辑像素。
- gfx.clear(color)、gfx.rect(x,y,w,h,color)、gfx.line、gfx.circle(x,y,r,color)、gfx.text(x,y,text,color)、gfx.text_width(text)。
- 颜色是 ARGB 数字；6 位当不透明。clear(0) 清空。每帧先 clear 再画。
- 写 function onFrame(dt) 才会每帧刷新。点在较小的图形上会 onPointer({ action, x, y })，action 是 down/move/up/cancel。铺满屏幕的 clear、横条、大圆只是画面，不吃触摸。gfx 不是壁纸，用户提到壁纸时不要用这段。

语音：asr.warm()；asr.ready / asr.hasModel / asr.listening / asr.deaf。按住角色 asr.start()，松开 asr.stop()。只在按住说话时 start，不要在拖动时 start。识别走 onSpeech({ text, partial, error? })。partial 为 false 才是一句完整的话。聊天球的「说」会抢走麦克风，这时 asr.start 失败，onSpeech 带 error。

模型决策：llm.ready / llm.provider / llm.model。llm.chat({ messages:[{role,content,image?}], system? }) 同步返回 { text, error, provider, model }。用户消息的 image 是 shot.take() 的 b64，或 data URL。key 由宿主代发，脚本拿不到。只支持 OpenAI 兼容后端。不要在 onFrame 或 onWallpaper 里调用。tts.say(text) 朗读，tts.speaking 为真；结束 onDone()。朗读时宿主会关掉脚本麦克风，播完短时间 asr.deaf，避免它听见自己。不要在 onDone 里立刻 asr.start。
截整个屏幕：shot.take() → { b64, mime, w, h, error }。包含桌面图标和当前应用。第一次系统会弹出确认，选整个屏幕。不要提无障碍。不要在 onFrame 或 onWallpaper 里调用。

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
    {
      name: "browser_open",
      label: "打开网页",
      description:
        "用内置浏览器打开一个 https 网页，显示在应用里，并返回标题和正文。用户要看网站时用。不要说没有浏览器。",
      parameters: Type.Object({
        url: Type.String({ description: "https 网址，可省略协议" }),
      }),
      execute: async (_id, params) => {
        const text = host.browserOpen(params.url || "");
        return { content: [{ type: "text", text: text || "页面是空的" }] };
      },
    },
    {
      name: "browser_act",
      label: "操作网页",
      description:
        "操作当前内置浏览器。action 是 click、type、scroll、key、select、back。target 写可见文字或 css 选择器。type 的 text 替换输入框整段。key 是 Enter、Tab、Escape、Backspace。scroll 的 dy 向下为正。返回操作结果和新的页面正文。",
      parameters: Type.Object({
        action: Type.String({ description: "click、type、scroll、key、select、back" }),
        target: Type.Optional(Type.String({ description: "控件上的文字，或 css 选择器" })),
        text: Type.Optional(Type.String({ description: "要输入的文字，或下拉选项" })),
        key: Type.Optional(Type.String({ description: "Enter、Tab、Escape、Backspace、ArrowUp、ArrowDown" })),
        dy: Type.Optional(Type.Number({ description: "滚动像素，向下为正" })),
      }),
      execute: async (_id, params) => {
        const text = host.browserAct(JSON.stringify({
          action: params.action || "",
          target: params.target || "",
          text: params.text || "",
          key: params.key || "",
          dy: typeof params.dy === "number" ? params.dy : 0,
        }));
        return { content: [{ type: "text", text: text || "页面是空的" }] };
      },
    },
    {
      name: "browser_eval",
      label: "网页脚本",
      description:
        "在当前网页里执行一段 JavaScript，返回它的结果。用 document 读结构、点击或填值。不要读取 cookie、localStorage、sessionStorage。",
      parameters: Type.Object({
        code: Type.String({ description: "在页面里执行的 JavaScript" }),
      }),
      execute: async (_id, params) => {
        const text = host.browserRun(params.code || "");
        return { content: [{ type: "text", text: text || "完成" }] };
      },
    },
    {
      name: "browser_read",
      label: "读网页",
      description: "再读当前网页，返回标题、正文，以及可见控件的标签和选择器。不打开新网址。",
      parameters: Type.Object({}),
      execute: async () => {
        const text = host.browserRead();
        return { content: [{ type: "text", text: text || "页面是空的" }] };
      },
    },
    {
      name: "screen_shot",
      label: "看屏幕",
      description:
        "截当前整个屏幕并作为图片返回，含桌面图标和正在前台的应用。装上或改完之后用它检查效果。第一次系统会弹出确认，请用户选整个屏幕。不要提无障碍。当前模型不收图片时只返回说明。",
      parameters: Type.Object({}),
      execute: async () => {
        const pic = host.screenShot() || {};
        if (!pic.b64 || pic.error) {
          return { content: [{ type: "text", text: pic.error || "截不到屏幕" }] };
        }
        const input = agent && agent.state && agent.state.model && agent.state.model.input;
        const sees = Array.isArray(input) && input.indexOf("image") >= 0;
        if (!sees) {
          return {
            content: [{ type: "text", text: "截到了 " + pic.w + "x" + pic.h + "，但当前模型不收图片。" }],
          };
        }
        return {
          content: [
            { type: "text", text: "当前整个屏幕。" },
            { type: "image", data: pic.b64, mimeType: pic.mime || "image/jpeg" },
          ],
        };
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

async function prompt(text, imagesJson) {
  if (!agent) throw new Error("agent 还没启动");
  try {
    let images;
    if (imagesJson) {
      const raw = JSON.parse(String(imagesJson));
      if (Array.isArray(raw) && raw.length) {
        const input = (agent.state.model && agent.state.model.input) || [];
        if (input.indexOf("image") < 0) {
          hostEvent("error", { text: "当前模型不收图片" });
          return;
        }
        images = raw.map((img) => ({
          type: "image",
          data: img.data,
          mimeType: img.mimeType || "image/jpeg",
        }));
      }
    }
    const body = String(text || "").trim() || (images ? "看这张图" : "");
    if (!body) return;
    OcaHost.log("prompt " + body.slice(0, 80) + (images ? " +图" : ""));
    await agent.prompt(body, images);
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
