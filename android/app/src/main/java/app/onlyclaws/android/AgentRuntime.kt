package app.onlyclaws.android

import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.util.Log
import com.caoccao.javet.enums.V8ValueErrorType
import com.caoccao.javet.interop.V8Host
import com.caoccao.javet.interop.V8Runtime
import com.caoccao.javet.interop.callback.IJavetDirectCallable
import com.caoccao.javet.interop.callback.JavetCallbackContext
import com.caoccao.javet.interop.callback.JavetCallbackType
import com.caoccao.javet.values.V8Value
import com.caoccao.javet.values.reference.V8ValueFunction
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONObject
import java.io.File
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * A separate V8 isolate that runs bundled pi-agent-core + pi-ai.
 * App scripts stay in [JsContainer]; this isolate is only the agent.
 */
class AgentRuntime(private val app: OcApp) {
    private val thread = Executors.newSingleThreadExecutor { r -> Thread(r, "oca-agent").apply { isDaemon = true } }
    private val io = Executors.newCachedThreadPool { r -> Thread(r, "oca-agent-io").apply { isDaemon = true } }
    private val watch = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "oca-agent-timer").apply { isDaemon = true }
    }
    private val main = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .followRedirects(true)
        .followSslRedirects(true)
        .onlyHttps()
        .build()
    private val streams = ConcurrentHashMap<Int, Stream>()
    private val timers = ConcurrentHashMap<Int, ScheduledFuture<*>>()
    private val nextStream = AtomicInteger(1)
    private val listeners = mutableSetOf<(AgentEvent) -> Unit>()
    private var runtime: V8Runtime? = null
    private var promptFn: V8ValueFunction? = null
    private var abortFn: V8ValueFunction? = null
    @Volatile var ready = false
        private set
    @Volatile var info = ""
        private set

    val store = AgentStore(app.filesDir)

    fun watch(listener: (AgentEvent) -> Unit) {
        main.post {
            listeners += listener
        }
    }

    fun unwatch(listener: (AgentEvent) -> Unit) {
        main.post { listeners -= listener }
    }

    fun start() {
        thread.execute { boot() }
    }

    fun reload() {
        thread.execute {
            close()
            boot()
        }
    }

    fun prompt(text: String, imageJpeg: ByteArray? = null) {
        thread.execute {
            val fn = promptFn
            val rt = runtime
            if (fn == null || rt == null) {
                emit(AgentEvent("error", """{"text":"agent 还没启动"}"""))
                return@execute
            }
            if (store.key(store.settings().provider).isEmpty() && store.settings().custom == null) {
                emit(AgentEvent("error", """{"text":"先在设置里配一家后端的 API key"}"""))
                return@execute
            }
            val args = mutableListOf<V8Value>(rt.createV8ValueString(text))
            if (imageJpeg != null && imageJpeg.isNotEmpty()) {
                val b64 = android.util.Base64.encodeToString(imageJpeg, android.util.Base64.NO_WRAP)
                args += rt.createV8ValueString("""[{"data":"$b64","mimeType":"image/jpeg"}]""")
            }
            runCatching {
                val result = fn.call<V8Value>(rt.createV8ValueUndefined(), *args.toTypedArray())
                try {
                    pump(rt)
                } finally {
                    result.close()
                }
            }.onFailure {
                Log.e(TAG, "prompt", it)
                emit(AgentEvent("error", JSONObject().put("text", it.message ?: "prompt 失败").toString()))
            }
            args.forEach { runCatching { it.close() } }
        }
    }

    fun abort() {
        thread.execute {
            val fn = abortFn ?: return@execute
            val rt = runtime ?: return@execute
            runCatching { fn.callVoid(rt.createV8ValueUndefined(), *emptyArray<V8Value>()) }
        }
    }

    fun install(title: String, source: String): String {
        val code = source.trim()
        val problem = HarnessText.check(code)
        if (problem != null) return problem
        val marked = HarnessText.MARK + "\n" + code
        val logs = java.util.Collections.synchronizedList(mutableListOf<String>())
        val tap: (String) -> Unit = { logs += it }
        app.tap(tap)
        val since = System.currentTimeMillis()
        var result = ""
        val done = CountDownLatch(1)
        app.load(marked) { r ->
            result = r.exceptionOrNull()?.message.orEmpty()
            done.countDown()
        }
        if (!done.await(90, TimeUnit.SECONDS)) result = "onStart 太久没返回"
        if (result.isEmpty()) {
            Thread.sleep(1500)
            val err = app.lastScriptError
            if (err != null && err.at >= since) result = "运行时出错：${err.text}"
        }
        app.untap(tap)
        if (result.isNotEmpty()) return HarnessText.diagnose(result, code, logs)
        app.container.writeActive(app, marked)
        return "已换上：${title.ifBlank { HarnessText.title(code) }}"
    }

    fun unload(): String {
        val boot = app.assets.open("boot.js").bufferedReader().readText()
        val done = CountDownLatch(1)
        var result = ""
        app.load(boot) { r ->
            result = r.exceptionOrNull()?.message.orEmpty()
            done.countDown()
        }
        done.await(20, TimeUnit.SECONDS)
        FileActive.clear(app)
        return if (result.isEmpty()) "已卸掉，屏幕空着" else result
    }

    private fun boot() {
        try {
            val rt = V8Host.getV8Instance().createV8Runtime<V8Runtime>()
            runtime = rt
            bindHost(rt)
            val code = app.assets.open("agent/pi.js").bufferedReader().readText()
            rt.getExecutor(code).setResourceName("pi.js").executeVoid()
            val start = rt.globalObject.get<V8Value>("OcaAgent").use { agent ->
                (agent as com.caoccao.javet.values.reference.V8ValueObject)
                    .get<V8ValueFunction>("start")
            }
            start.use { fn ->
                val host = rt.globalObject.get<V8Value>("OcaHost")
                host.use {
                    val infoValue = fn.call<V8Value>(rt.createV8ValueUndefined(), it, rt.createV8ValueString(store.settingsJson()))
                    infoValue.use { info = rt.converter.toObject<Any?>(it)?.toString().orEmpty() }
                }
            }
            val agent = rt.globalObject.get<com.caoccao.javet.values.reference.V8ValueObject>("OcaAgent")
            agent.use {
                promptFn = it.get("prompt")
                abortFn = it.get("abort")
            }
            ready = true
            File(app.filesDir, "agent/catalog.json").writeText(info.ifBlank { "{}" })
            emit(AgentEvent("ready", info))
            Log.i(TAG, "pi agent ready $info")
        } catch (t: Throwable) {
            ready = false
            Log.e(TAG, "pi agent failed", t)
            emit(AgentEvent("error", JSONObject().put("text", "agent 启动失败：${t.message}").toString()))
        }
    }

    private fun bindHost(rt: V8Runtime) {
        rt.createV8ValueObject().use { obj ->
            fun fn(name: String, body: (Array<out V8Value>) -> Any?) {
                obj.bindFunction(
                    JavetCallbackContext(
                        name,
                        JavetCallbackType.DirectCallNoThisAndResult,
                        IJavetDirectCallable.NoThisAndResult<Exception> { args ->
                            try {
                                val v = body(args ?: emptyArray())
                                if (v is V8Value) v else toV8(rt, v)
                            } catch (e: Exception) {
                                rt.throwError(V8ValueErrorType.Error, e.message ?: e.javaClass.simpleName)
                                rt.createV8ValueUndefined()
                            }
                        },
                    ),
                )
            }
            fn("getKey") { store.key(string(rt, it, 0)) }
            fn("random") { n ->
                val size = (n.getOrNull(0)?.let { rt.converter.toObject<Any?>(it) } as? Number)?.toInt() ?: 0
                val bytes = ByteArray(size.coerceIn(0, 4096))
                java.security.SecureRandom().nextBytes(bytes)
                bytes.map { it.toInt() and 255 }
            }
            fn("uuid") { UUID.randomUUID().toString() }
            fn("timerStart") { args ->
                val id = intOf(rt, args, 0)
                val ms = intOf(rt, args, 1).toLong().coerceAtLeast(0)
                timers.remove(id)?.cancel(false)
                timers[id] = watch.schedule({ thread.execute { fireTimer(id) } }, ms, TimeUnit.MILLISECONDS)
            }
            fn("timerClear") { args ->
                timers.remove(intOf(rt, args, 0))?.cancel(false)
            }
            fn("fetchStart") { args -> fetchStart(string(rt, args, 0), string(rt, args, 1)) }
            fn("fetchRead") { args ->
                val id = intOf(rt, args, 0)
                streams[id]?.read() ?: mapOf("done" to true)
            }
            fn("fetchCancel") { args ->
                streams.remove(intOf(rt, args, 0))?.close()
            }
            fn("installApp") { args -> install(string(rt, args, 0), string(rt, args, 1)) }
            fn("readApp") { app.container.readActive(app) ?: "" }
            fn("unloadApp") { unload() }
            fn("readLogs") { app.lines.joinToString("\n") }
            fn("screenShot") { ScreenGrab.capture() }
            fn("browserOpen") { args -> app.overlay.web.browse(string(rt, args, 0)) }
            fn("browserRead") { app.overlay.web.readPage() }
            fn("browserAct") { args -> app.overlay.web.act(string(rt, args, 0)) }
            fn("browserRun") { args -> app.overlay.web.run(string(rt, args, 0)) }
            fn("event") { args ->
                emit(AgentEvent(string(rt, args, 0), string(rt, args, 1)))
            }
            fn("log") { args ->
                val line = string(rt, args, 0)
                Log.i(TAG, line)
                app.append("agent：$line")
            }
            rt.globalObject.set("OcaHost", obj)
        }
    }

    private fun fetchStart(url: String, specJson: String): Map<String, Any?> {
        val id = nextStream.getAndIncrement()
        val spec = JSONObject(specJson)
        val httpUrl = url.toHttpUrl()
        if (httpUrl.scheme != "https") throw IllegalArgumentException("只接受 https")
        val method = spec.optString("method", "GET").uppercase()
        val builder = Request.Builder().url(httpUrl)
        val headers = spec.optJSONObject("headers")
        if (headers != null) {
            val keys = headers.keys()
            while (keys.hasNext()) {
                val name = keys.next()
                builder.header(name, headers.optString(name))
            }
        }
        val body = spec.optString("body", "").takeIf { spec.has("body") && !spec.isNull("body") && it.isNotEmpty() }
        if (body != null) {
            val type = headers?.optString("Content-Type")?.toMediaTypeOrNull()
            builder.method(method, body.toRequestBody(type))
        } else {
            builder.method(method, null)
        }
        val done = CountDownLatch(1)
        var result: Map<String, Any?>? = null
        var error: Throwable? = null
        io.execute {
            try {
                val response = http.newCall(builder.build()).execute()
                val headerMap = linkedMapOf<String, String>()
                for (name in response.headers.names()) {
                    headerMap[name] = response.headers.values(name).joinToString(", ")
                }
                val bytes = response.body?.bytes() ?: ByteArray(0)
                response.close()
                streams[id] = Stream(bytes)
                Log.i(TAG, "fetch $id ${response.code} ${bytes.size}b $url")
                result = mapOf("id" to id, "status" to response.code, "headers" to headerMap)
            } catch (t: Throwable) {
                Log.e(TAG, "fetch $url", t)
                error = t
            } finally {
                done.countDown()
            }
        }
        if (!done.await(180, TimeUnit.SECONDS)) throw IllegalStateException("fetch 超时")
        error?.let { throw it }
        return result ?: throw IllegalStateException("fetch 没有返回")
    }

    private fun fireTimer(id: Int) {
        val rt = runtime ?: return
        runCatching {
            rt.globalObject.get<com.caoccao.javet.values.reference.V8ValueObject>("OcaHost").use { host ->
                host.invokeVoid("onTimer", id)
            }
            pump(rt)
        }
    }

    /** Drain microtasks without waiting for pending host/timer promises. */
    private fun pump(rt: V8Runtime) {
        repeat(64) { runCatching { rt.getExecutor("void 0").executeVoid() } }
    }

    private fun emit(event: AgentEvent) {
        main.post { listeners.forEach { it(event) } }
    }

    private fun close() {
        ready = false
        promptFn?.close()
        abortFn?.close()
        promptFn = null
        abortFn = null
        streams.values.forEach { it.close() }
        streams.clear()
        timers.values.forEach { it.cancel(false) }
        timers.clear()
        runtime?.close()
        runtime = null
    }

    private fun toV8(rt: V8Runtime, value: Any?): V8Value = when (value) {
        null, Unit -> rt.createV8ValueUndefined()
        else -> rt.converter.toV8Value(rt, value)
    }

    private class Stream(bytes: ByteArray) {
        private val data = bytes
        private var offset = 0
        fun read(): Map<String, Any> {
            if (offset >= data.size) return mapOf("done" to true)
            val end = minOf(offset + 8192, data.size)
            val buf = data.copyOfRange(offset, end)
            offset = end
            return mapOf("done" to false, "b64" to Base64.encodeToString(buf, Base64.NO_WRAP))
        }
        fun close() {
            offset = data.size
        }
    }

    companion object {
        private const val TAG = "OCA-PI"
        private fun string(rt: V8Runtime, args: Array<out V8Value>, i: Int): String {
            val v = args.getOrNull(i) ?: return ""
            return rt.converter.toObject<Any?>(v)?.toString().orEmpty()
        }
        private fun intOf(rt: V8Runtime, args: Array<out V8Value>, i: Int): Int =
            (rt.converter.toObject<Any?>(args.getOrNull(i)) as? Number)?.toInt() ?: 0
    }
}

data class AgentEvent(val type: String, val payload: String)

object FileActive {
    fun clear(app: OcApp) {
        java.io.File(app.filesDir, "active.js").delete()
    }
}
