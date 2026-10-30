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

apps_install 会把一段 JavaScript 装进本机脚本容器。脚本环境是 V8，host API 是同步的，没有 setTimeout。
钩子必须写成 function onStart() / onAction(e) / onFrame(dt) / onStop()。
生成脚本可用：a2ui（v0.9）、tts、http.request（同步 https）、wallpaper、oca.log。
没有 keys、web、desk。做不到的事先在聊天里说。

界面（A2UI v0.9）：
1. onStart 里先发 a2ui.send({ version: "v0.9", createSurface: { surfaceId: "main", catalogId: a2ui.catalog } })，只发一次。
2. 数据：a2ui.send({ version: "v0.9", updateDataModel: { surfaceId: "main", path: "/", value: { draft: "" } } })。
3. 组件：a2ui.send({ version: "v0.9", updateComponents: { surfaceId: "main", components: [...] } })，必须有 id 为 root 的组件。

装上失败时，工具会返回报错、出错的那一行和试装日志。根据这些自己查原因再改，不要用 try/catch 把错误吞掉。`;

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
    streamFn: models.streamSimple.bind(models),
    getApiKey: (provider) => host.getKey(provider) || undefined,
    identity: { attribution: { name: "OnlyClaws", url: "https://onlyclaws.app" } },
  });
  agent.subscribe((event) => {
    host.event(event.type, JSON.stringify(event));
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
  await agent.prompt(String(text || ""));
}

function abort() {
  agent?.abort();
}

globalThis.OcaAgent = { start, prompt, abort, catalog };
