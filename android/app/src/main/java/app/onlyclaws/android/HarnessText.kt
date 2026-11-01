package app.onlyclaws.android

import com.caoccao.javet.exceptions.BaseJavetScriptingException
import com.caoccao.javet.interop.V8Host
import com.caoccao.javet.interop.V8Runtime

/** What the harness says to the model, and how it reads the reply. No Android here. */
object HarnessText {
    /** First line of every script the harness writes. [OcApp] installs fewer plugins for such scripts. */
    const val MARK = "// oca:generated"

    val SYSTEM = """
你在一台安卓手机上，把用户说的一句话做成一个马上能用的小程序。只回一段完整的 JavaScript，放在 ```js 代码块里，不写解释。

运行环境是 V8，可以用现代 JavaScript（let、const、箭头函数、class、模板字符串）。下面的全局函数都是同步的，没有 setTimeout、setInterval 和其它定时器。
第一行写 `// 标题：` 加不超过 12 个字的名字。

钩子必须写成 function onStart() {…} 这样的函数声明，写成 const onStart = … 不会被调用：
- onStart()：装上时调用一次，在这里建界面。
- onAction(e)：用户点了按钮。e.action 是按钮 action.event.name，e.context 是 event.context 里的值（路径已经取成值）。
- onFrame(dt)：可选，每帧调用，dt 单位秒。不需要动画或计时就不要写。
- onStop()：被换下时调用。

能用的全局对象：
- gfx / ui：系统浮层。gfx.clear、rect、line、circle、text、text_width。颜色 ARGB。写 onFrame(dt) 才刷新。onPointer({action,x,y})。
- asr：asr.warm / start / stop。onSpeech({text, partial, error?})。
- llm.chat({ messages, system? })：宿主代发，返回 { text, error }。不要在 onFrame 里调用。
- tts.say(文字)、tts.stop()：朗读。tts.speaking。结束 onDone()。朗读时脚本麦克风会被关掉。
- a2ui.send(消息)：应用内界面，A2UI v0.9。a2ui.catalog 是目录号。
- http.request({ url, method, headers, body, timeoutMs })：同步 https，没有密钥。
- wallpaper、oca.log。
没有 keys、web、desk。做不到的事，在界面上直接说明做不到。

界面（A2UI v0.9 基础目录）：
1. onStart 里先发 a2ui.send({ version: "v0.9", createSurface: { surfaceId: "main", catalogId: a2ui.catalog } })，只发一次。
2. 输入框的值放在数据模型里：a2ui.send({ version: "v0.9", updateDataModel: { surfaceId: "main", path: "/", value: { draft: "" } } })。
3. 组件平铺成数组发出：a2ui.send({ version: "v0.9", updateComponents: { surfaceId: "main", components: [...] } })。必须有一个 id 为 "root" 的组件，子组件用 id 引用，id 不能重复。
组件（component 字段）和常用属性：
- Text：text，variant（h1 h2 h3 h4 h5 body caption）
- Image：url，fit（contain cover fill），variant
- Row、Column：children（id 数组），justify（start center end spaceBetween spaceAround spaceEvenly stretch），align（start center end stretch）
- List：children，direction（vertical horizontal）
- Card：child
- Divider
- Button：child（一个 Text 的 id），variant（primary default borderless），action：{ event: { name: "动作名", context: { 键: 值或 { path: "/路径" } } } }
- TextField：label，value：{ path: "/路径" }，variant（shortText longText number obscured）
- CheckBox：label，value
- Slider：label，min，max，value
- ChoicePicker：options，value，variant（mutuallyExclusive multipleSelection）
文字属性可以是字符串，也可以是 { path: "/路径" }。按钮要拿到输入框里的字，就在 event.context 里写 { path: "/路径" }。
界面要变时，在 JS 里重新生成整个组件数组再发一次 updateComponents；列表项用 "item0"、"item1" 这样的 id 逐个生成。不要再发 createSurface。

例子：
```js
// 标题：待办
const items = [];
function draw() {
  const comps = [
    { id: "root", component: "Column", children: ["title", "input", "add", "list"] },
    { id: "title", component: "Text", text: "待办", variant: "h2" },
    { id: "input", component: "TextField", label: "要做什么", value: { path: "/draft" } },
    { id: "addText", component: "Text", text: "添加" },
    { id: "add", component: "Button", child: "addText", variant: "primary",
      action: { event: { name: "add", context: { text: { path: "/draft" } } } } }
  ];
  const ids = items.map((text, i) => {
    comps.push({ id: "item" + i, component: "Text", text });
    return "item" + i;
  });
  comps.push({ id: "list", component: "Column", children: ids });
  a2ui.send({ version: "v0.9", updateComponents: { surfaceId: "main", components: comps } });
}
function onStart() {
  a2ui.send({ version: "v0.9", createSurface: { surfaceId: "main", catalogId: a2ui.catalog } });
  a2ui.send({ version: "v0.9", updateDataModel: { surfaceId: "main", path: "/", value: { draft: "" } } });
  draw();
}
function onAction(e) {
  if (e.action === "add" && e.context?.text) {
    items.push(String(e.context.text));
    a2ui.send({ version: "v0.9", updateDataModel: { surfaceId: "main", path: "/draft", value: "" } });
    draw();
  }
}
```
""".trim()

    fun userPrompt(request: String, current: String?, recent: List<String>, runtimeError: String): String {
        val out = StringBuilder()
        if (recent.isNotEmpty()) {
            out.append("之前说过：\n")
            recent.forEachIndexed { i, line -> out.append(i + 1).append(". ").append(line).append('\n') }
            out.append('\n')
        }
        out.append("现在要的：").append(request.trim()).append('\n')
        if (current != null) {
            out.append("\n手机上正在跑的脚本如下。在它的基础上改，用户没要求去掉的功能都留着：\n```js\n")
            out.append(current.removePrefix(MARK).trimStart('\n')).append("\n```\n")
        }
        if (runtimeError.isNotEmpty()) {
            out.append("\n这份脚本运行时报过错：").append(runtimeError).append("\n顺手改掉。\n")
        }
        return out.toString()
    }

    fun retryPrompt(problem: String): String =
        "这一版没装上：$problem\n先根据上面的报错、出错那一行和日志找出原因，再改。" +
            "不要用 try/catch 把错误吞掉。改好后重新给出完整脚本，仍然只回一个 ```js 代码块。"

    /**
     * What went wrong while the script was installed and running, in terms of the code the model wrote.
     * [code] is installed one line below [MARK], so reported lines are moved up by one.
     */
    fun diagnose(problem: String, code: String, logs: List<String>): String {
        val lines = code.lines()
        val cited = sortedSetOf<Int>()
        val text = LINE.replace(problem) { m ->
            val n = m.groupValues[1].toInt() - 1
            if (n in 1..lines.size) cited += n
            "第 $n 行"
        }
        val out = StringBuilder(text)
        for (n in cited) out.append("\n第 $n 行是：").append(lines[n - 1].trim().take(LINE_CHARS))
        val tail = logs.takeLast(LOG_LINES).map { LINE.replace(it) { m -> "第 ${m.groupValues[1].toInt() - 1} 行" } }
        if (tail.isNotEmpty()) {
            out.append("\n试装时的日志：")
            tail.forEach { out.append("\n- ").append(it.take(LINE_CHARS)) }
        }
        return out.toString()
    }

    /** The first fenced block, or the whole reply when it is plainly a script. */
    fun extractScript(reply: String): String? {
        val fence = FENCE.find(reply)
        val code = fence?.groupValues?.get(1) ?: reply.takeIf { ON_START.containsMatchIn(it) }
        return code?.trim()?.takeIf { it.isNotEmpty() }
    }

    fun title(code: String): String =
        TITLE.find(code)?.groupValues?.get(1)?.trim()?.take(24)?.ifEmpty { null } ?: "新界面"

    fun looksLikeKey(text: String): Boolean = KEY.matches(text.trim())

    /** Empty when the script compiles and defines onStart. Same language level as the container. */
    fun check(code: String): String? {
        try {
            V8Host.getV8Instance().createV8Runtime<V8Runtime>().use { rt ->
                rt.getExecutor(code).setResourceName("script.js").compileV8Script().close()
            }
        } catch (e: BaseJavetScriptingException) {
            return "第 ${e.scriptingError.lineNumber} 行语法错误：${e.scriptingError.message}"
        }
        if (!ON_START.containsMatchIn(code)) return "没有 onStart"
        return null
    }

    private val FENCE = Regex("```(?:js|javascript|JavaScript)?[ \\t]*\\r?\\n([\\s\\S]*?)```")
    private val ON_START = Regex("function\\s+onStart\\s*\\(")
    private val TITLE = Regex("^\\s*//\\s*标题\\s*[:：]\\s*(.+)$", RegexOption.MULTILINE)
    private val KEY = Regex("sk-[A-Za-z0-9_-]{16,}")
    private val LINE = Regex("第 (\\d+) 行")
    private const val LOG_LINES = 20
    private const val LINE_CHARS = 200
}
