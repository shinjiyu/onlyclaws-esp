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
- onAction(e)：用户点了带 data-action 的元素。e.action 是动作名，e.context 是当时各 data-field 的值。
- onFrame(dt)：可选，每帧调用，dt 单位秒。不需要动画或计时就不要写。
- onStop()：被换下时调用。

用户说出「壁纸」（含桌面背景、换壁纸、星空壁纸、去掉壁纸）时，脚本里只能调用 wallpaper.load 或 wallpaper.clear。禁止 gfx、screen、onFrame 画壁纸。
- 纯色：wallpaper.load({ color: 0x05060e, text, textColor, size, x, y })。color 是 RGB 或 ARGB 数字。
- 会动的预设只有 wallpaper.load({ scene: "crash" })。
- 去掉：wallpaper.clear()。
星空、银河、夜空也用 wallpaper.load({ color: 0x05060e })。没有逐颗画星星的接口。做不到的部分用界面上的文字说明，不要改用 gfx.circle。

能用的全局对象：
- gfx / ui：系统浮层，盖在图标上面，不是壁纸。gfx.clear、rect、line、circle、text、text_width。颜色 ARGB。写 onFrame(dt) 才刷新。onPointer 只落在较小的图形上。铺满屏幕的底色、横条和大圆不吃触摸。用户提到壁纸时不要用 gfx。
- asr：asr.warm / start / stop。onSpeech({text, partial, error?})。
- llm.chat({ messages, system? })：宿主代发，返回 { text, error }。不要在 onFrame 里调用。
- tts.say(文字)、tts.stop()：朗读。tts.speaking。结束 onDone()。朗读时脚本麦克风会被关掉。
- screen.show(html) / screen.clear()：应用主界面。一段内嵌 HTML，可以用 SVG 和 CSS。没有 a2ui。可点处写 data-action，输入框写 data-field。点击调用 onAction({ action, context })。不能打开链接，不能加载网络资源。
- http.request({ url, method, headers, body, timeoutMs }) 和 fetch(url, init)：同步 https，没有密钥。http.request 返回 { status, body, error, headers }。fetch 另外有 ok、text()、json()。脚本可以上网，不要写成做不到。
- socket.open({ host, port, timeoutMs }) → { id, error }。socket.send(id, { text } 或 { b64 })。socket.recv(id, { maxBytes, timeoutMs }) → { text, b64, n, eof, error }。socket.close(id)。只能连出去，不能监听。
- ssh.exec({ host, port, user, password 或 privateKey, command, timeoutMs }) → { code, stdout, stderr, error, fingerprint }。一条命令后断开。主机指纹变了会拒绝。密码不要画出来。不要在 onFrame 里调用 socket 或 ssh。
- wallpaper：见上面的壁纸规则。只有 load 和 clear。壁纸在图标后面，不接管滑动。
- oca.log。
没有 keys、web、desk。做不到的事，在界面上直接说明做不到。

界面要变时，重新拼好整段 HTML，再调用一次 screen.show。不要用 gfx 画主界面。桌宠才用 gfx。

例子：
```js
// 标题：待办
const items = [];
function draw() {
  const list = items.map((text) => "<p>" + String(text).replace(/[&<>]/g, "") + "</p>").join("");
  screen.show(
    "<h2>待办</h2><input data-field=\"draft\"><button data-action=\"add\">添加</button>" + list
  );
}
function onStart() {
  draw();
}
function onAction(e) {
  if (e.action === "add" && e.context && e.context.draft) {
    items.push(String(e.context.draft));
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
