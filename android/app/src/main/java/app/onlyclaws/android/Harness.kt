package app.onlyclaws.android

import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import java.util.ArrayDeque
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

data class HarnessState(val text: String, val working: Boolean)

/**
 * Stays in the APK while scripts come and go. One request at a time: ask the model for a
 * whole script, compile it, install it with the generated-script plugins, and hand any
 * error back for another try. When every try fails, the script from before is put back.
 */
class Harness(private val app: OcApp) {
    private val io = Executors.newSingleThreadExecutor()
    private val call = HttpCall(HttpCall.client())
    private val main = Handler(Looper.getMainLooper())
    private val busy = AtomicBoolean(false)
    private val listeners = mutableSetOf<(HarnessState) -> Unit>()
    private val recent = ArrayDeque<String>()

    @Volatile
    private var runtimeError = ""

    @Volatile
    private var runtimeErrorAt = 0L

    var state = HarnessState(if (hasKey()) "说一句话，或者打字" else "先粘贴 DeepSeek key（sk- 开头）", false)
        private set

    init {
        app.container.onError = { message ->
            runtimeError = message
            runtimeErrorAt = System.currentTimeMillis()
        }
    }

    fun ask(raw: String) {
        val text = raw.trim()
        if (text.isEmpty()) return
        if (HarnessText.looksLikeKey(text)) {
            val saved = app.keys.write(KEY_NAME, text)
            post(if (saved) "DeepSeek key 已存好，说说想要什么" else "key 没存上", false)
            return
        }
        val key = app.keys.read(KEY_NAME)
        if (key.isEmpty()) {
            post("先粘贴 DeepSeek key（sk- 开头）", false)
            return
        }
        if (!busy.compareAndSet(false, true)) {
            post("还在做上一个，稍等", true)
            return
        }
        post("收到：$text", true)
        io.execute {
            try {
                build(text, key)
            } catch (t: Throwable) {
                post("出错了：${t.message}", false)
            } finally {
                busy.set(false)
            }
        }
    }

    fun watch(listener: (HarnessState) -> Unit) {
        main.post {
            listeners += listener
            listener(state)
        }
    }

    fun unwatch(listener: (HarnessState) -> Unit) {
        main.post { listeners -= listener }
    }

    private fun hasKey() = app.keys.read(KEY_NAME).isNotEmpty()

    private fun build(request: String, key: String) {
        val before = app.container.readActive(app)
        val current = before?.takeIf { it.startsWith(HarnessText.MARK) }
        if (current == null) recent.clear()
        val messages = JSONArray()
            .put(message("system", HarnessText.SYSTEM))
            .put(message("user", HarnessText.userPrompt(request, current, recent.toList(), if (current == null) "" else runtimeError)))
        var problem = ""
        var swapped = false
        for (attempt in 1..TRIES) {
            post(if (attempt == 1) "正在写" else "第 $attempt 次重写：${problem.lineSequence().first()}", true)
            val reply = chat(key, messages)
            if (reply.error.isNotEmpty()) {
                problem = reply.error
                break
            }
            messages.put(message("assistant", reply.text))
            val code = HarnessText.extractScript(reply.text)
            problem = if (code == null) "没有给出代码块" else HarnessText.check(code).orEmpty()
            if (code != null && problem.isEmpty()) {
                post("正在试装", true)
                val source = HarnessText.MARK + "\n" + code
                val since = System.currentTimeMillis()
                val logs = Collections.synchronizedList(mutableListOf<String>())
                val tap: (String) -> Unit = { logs += it }
                app.tap(tap)
                try {
                    problem = install(source)
                    if (problem.isEmpty()) {
                        swapped = true
                        Thread.sleep(SETTLE_MS)
                        if (runtimeErrorAt >= since) problem = "运行时出错：$runtimeError"
                    }
                } finally {
                    app.untap(tap)
                }
                if (problem.isNotEmpty()) problem = HarnessText.diagnose(problem, code, logs.toList())
                if (problem.isEmpty()) {
                    app.container.writeActive(app, source)
                    runtimeError = ""
                    recent.addLast(request)
                    while (recent.size > RECENT) recent.removeFirst()
                    post("已换上：${HarnessText.title(code)}", false)
                    return
                }
            }
            messages.put(message("user", HarnessText.retryPrompt(problem)))
        }
        if (swapped) main.post { app.reloadScript() }
        post("没做成：${problem.lineSequence().first()}。屏幕保持原样", false)
    }

    /** Empty when the script is in place. Blocks this thread until the container has tried it. */
    private fun install(source: String): String {
        val done = CountDownLatch(1)
        var problem = ""
        app.load(source) { result ->
            result.onFailure { problem = "装上时出错：${it.message.orEmpty()}" }
            done.countDown()
        }
        if (!done.await(INSTALL_WAIT_S, TimeUnit.SECONDS)) return "onStart 太久没返回"
        return problem
    }

    private fun chat(key: String, messages: JSONArray): Reply {
        val body = JSONObject()
            .put("model", MODEL)
            .put("messages", messages)
            .put("temperature", 0.2)
            .put("stream", false)
            .toString()
        val outcome = call.perform(
            HttpSpec(
                url = URL,
                method = "POST",
                headers = mapOf("Authorization" to "Bearer $key", "Content-Type" to "application/json"),
                body = body,
                timeoutMs = 120_000,
            ),
        )
        if (outcome.status == 401) return Reply(error = "DeepSeek key 不对，重新粘贴一个")
        if (outcome.status != 200) {
            val detail = if (outcome.status == 0) outcome.error else "HTTP ${outcome.status} ${apiError(outcome.body)}"
            return Reply(error = "模型没回：$detail".trim())
        }
        val text = runCatching {
            JSONObject(outcome.body).getJSONArray("choices").getJSONObject(0)
                .getJSONObject("message").getString("content")
        }.getOrNull()
        return if (text.isNullOrBlank()) Reply(error = "模型回复读不出来") else Reply(text = text)
    }

    private fun apiError(body: String): String =
        runCatching { JSONObject(body).getJSONObject("error").getString("message") }.getOrDefault("").take(120)

    private fun message(role: String, content: String) = JSONObject().put("role", role).put("content", content)

    private fun post(text: String, working: Boolean) {
        app.append(text)
        main.post {
            state = HarnessState(text, working)
            listeners.forEach { it(state) }
        }
    }

    private data class Reply(val text: String = "", val error: String = "")

    companion object {
        const val KEY_NAME = "deepseek"
        private const val MODEL = "deepseek-flash"
        private const val URL = "https://api.deepseek.com/v1/chat/completions"
        private const val TRIES = 3
        private const val RECENT = 6
        private const val SETTLE_MS = 1500L
        private const val INSTALL_WAIT_S = 90L
    }
}
