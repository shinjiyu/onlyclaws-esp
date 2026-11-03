package app.onlyclaws.android

import android.content.Context
import com.caoccao.javet.enums.V8ValueErrorType
import com.caoccao.javet.exceptions.BaseJavetScriptingException
import com.caoccao.javet.exceptions.JavetTerminatedException
import com.caoccao.javet.interop.V8Host
import com.caoccao.javet.interop.V8Runtime
import com.caoccao.javet.interop.callback.IJavetDirectCallable
import com.caoccao.javet.interop.callback.JavetCallbackContext
import com.caoccao.javet.interop.callback.JavetCallbackType
import com.caoccao.javet.values.V8Value
import com.caoccao.javet.values.primitive.V8ValueBoolean
import com.caoccao.javet.values.primitive.V8ValueNull
import com.caoccao.javet.values.primitive.V8ValueString
import com.caoccao.javet.values.primitive.V8ValueUndefined
import com.caoccao.javet.values.reference.V8ValueFunction
import com.caoccao.javet.values.reference.V8ValueObject
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * One V8 thread. Plugins install host objects; the shell calls in.
 * Every load gets a fresh runtime, so a failed load leaves the previous script in place.
 * Script code that runs [stuckMs] without coming back to a host call is terminated.
 */
class JsContainer(
    private val onLog: (String) -> Unit,
    private val stuckMs: Long = STUCK_MS,
) {
    private val thread = Executors.newSingleThreadExecutor { r -> Thread(r, "oca-js").apply { isDaemon = true } }
    private val watchdog = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "oca-js-watch").apply { isDaemon = true }
    }
    private val plugins = mutableListOf<JsPlugin>()
    private val frameBusy = AtomicBoolean(false)
    private val wallBusy = AtomicBoolean(false)
    private var runtime: V8Runtime? = null
    private var lastError = ""
    private var lastErrorAt = 0L
    private var hostDepth = 0
    private val gate = Any()

    @Volatile private var running: V8Runtime? = null
    @Volatile private var jsSince = 0L
    @Volatile private var stopped = false

    /** Errors after a script is in place: hooks, frames, the UI it drew. */
    @Volatile
    var onError: ((String) -> Unit)? = null

    init {
        watchdog.scheduleWithFixedDelay(::watch, WATCH_MS, WATCH_MS, TimeUnit.MILLISECONDS)
    }

    fun use(plugin: JsPlugin) {
        plugins += plugin
    }

    /** Only plugins that pass [allow] are installed into the new script's scope. */
    fun load(source: String, allow: (JsPlugin) -> Boolean = { true }, done: (Result<Unit>) -> Unit) {
        thread.execute {
            plugins.forEach { it.beforeSwap() }
            var pumps = false
            var wallpaper = false
            val result = runCatching {
                val hooks = swap(source, allow)
                pumps = hooks.first
                wallpaper = hooks.second
            }
            plugins.forEach { it.afterSwap(result.isSuccess, pumps) }
            if (result.isSuccess) plugins.forEach { it.wallpaperHook(wallpaper) }
            plugins.forEach { it.afterTurn() }
            done(result)
        }
    }

    /** Calls a global hook such as `onAction` with converted arguments. Skipped when the script has none. */
    fun fire(hook: String, vararg args: Any?) {
        thread.execute {
            val current = runtime ?: return@execute
            runCatching { callHook(current, hook, args) }.onFailure(::noteError)
            plugins.forEach { it.afterTurn() }
        }
    }

    /**
     * One wallpaper vsync. The wallpaper engine calls this while its surface is showing.
     * Dropped when the previous wallpaper frame is still on the script thread.
     */
    fun enterWallpaper(dt: Double) {
        if (!wallBusy.compareAndSet(false, true)) return
        thread.execute {
            try {
                val current = runtime ?: return@execute
                plugins.forEach { it.beforeWallpaper() }
                try {
                    runCatching { callHook(current, "onWallpaper", arrayOf(dt)) }.onFailure(::noteError)
                } finally {
                    plugins.forEach { it.afterWallpaper() }
                }
            } finally {
                wallBusy.set(false)
            }
        }
    }

    /** One vsync. Extra frames are dropped until this one returns. */
    fun enterFrame(dt: Double) {
        if (!frameBusy.compareAndSet(false, true)) return
        thread.execute {
            try {
                val current = runtime ?: return@execute
                runCatching { callHook(current, "onFrame", arrayOf(dt)) }.onFailure(::noteError)
                plugins.forEach { it.afterTurn() }
            } finally {
                frameBusy.set(false)
            }
        }
    }

    fun readActive(context: Context): String? {
        val file = File(context.filesDir, "active.js")
        if (!file.exists()) return null
        return file.readText().ifBlank { null }
    }

    fun writeActive(context: Context, source: String) {
        File(context.filesDir, "active.js").writeText(source)
    }

    fun report(message: String) {
        thread.execute { noteError(message) }
    }

    private fun swap(source: String, allow: (JsPlugin) -> Boolean): Pair<Boolean, Boolean> {
        val fresh = V8Host.getV8Instance().createV8Runtime<V8Runtime>()
        try {
            val scope = Scope(fresh)
            scope.define("oca") {
                fn("log") { args ->
                    onLog(args.string(0))
                    null
                }
            }
            plugins.filter(allow).forEach { it.install(scope) }
            script(fresh) {
                if (hasObject(fresh, "http")) fresh.getExecutor(FETCH).executeVoid()
                fresh.getExecutor(source).setResourceName(RESOURCE).executeVoid()
            }
            callHook(fresh, "onStart")
            val pumps = hasFunction(fresh, "onFrame")
            val wallpaper = hasFunction(fresh, "onWallpaper")
            val previous = runtime
            runtime = fresh
            plugins.forEach { it.setDrawing(false) }
            try {
                if (previous != null) runCatching { callHook(previous, "onStop") }.onFailure(::noteError)
            } finally {
                plugins.forEach { it.setDrawing(true) }
                previous?.let(::close)
            }
            return pumps to wallpaper
        } catch (t: Throwable) {
            if (runtime !== fresh) close(fresh)
            throw ScriptException(describe(t), t)
        }
    }

    private fun callHook(rt: V8Runtime, name: String, args: Array<out Any?> = emptyArray()) {
        rt.globalObject.get<V8Value>(name).use { fn ->
            if (fn !is V8ValueFunction) return
            val values = args.map { toV8(rt, it) }
            try {
                script(rt) {
                    fn.callVoid(rt.createV8ValueUndefined(), *values.toTypedArray())
                    rt.await()
                }
            } finally {
                values.forEach { it.close() }
            }
        }
    }

    private fun hasFunction(rt: V8Runtime, name: String): Boolean =
        rt.globalObject.get<V8Value>(name).use { it is V8ValueFunction }

    private fun hasObject(rt: V8Runtime, name: String): Boolean =
        rt.globalObject.get<V8Value>(name).use { it is V8ValueObject }

    /** Script code is running from here until it calls back into the host or returns. */
    private inline fun <T> script(rt: V8Runtime, block: () -> T): T {
        synchronized(gate) {
            running = rt
            stopped = false
            jsSince = System.nanoTime()
        }
        try {
            return block()
        } finally {
            synchronized(gate) {
                jsSince = 0L
                running = null
                if (stopped) {
                    rt.cancelTerminateExecution()
                    stopped = false
                }
            }
        }
    }

    /** Time spent inside a host call does not count against the script. */
    private inline fun host(block: () -> V8Value): V8Value {
        if (hostDepth++ == 0) synchronized(gate) { jsSince = 0L }
        try {
            return block()
        } finally {
            if (--hostDepth == 0) synchronized(gate) { if (running != null) jsSince = System.nanoTime() }
        }
    }

    private fun watch() = synchronized(gate) {
        val since = jsSince
        val rt = running ?: return
        if (since == 0L || stopped) return
        if (System.nanoTime() - since < TimeUnit.MILLISECONDS.toNanos(stuckMs)) return
        stopped = true
        rt.terminateExecution()
    }

    private fun close(rt: V8Runtime) {
        runCatching { rt.close() }
    }

    private fun describe(t: Throwable): String = when (t) {
        is JavetTerminatedException -> "脚本 ${stuckMs / 1000.0} 秒没有返回，已打断"
        is BaseJavetScriptingException -> {
            val error = t.scriptingError
            val line = error.lineNumber
            if (line > 0) "${error.message}（第 $line 行）" else error.message
        }
        is ScriptException -> t.message.orEmpty()
        else -> t.message?.lineSequence()?.firstOrNull().orEmpty().ifEmpty { t.javaClass.simpleName }
    }

    private fun noteError(t: Throwable) {
        noteError(describe(t))
    }

    private fun noteError(msg: String) {
        val now = System.currentTimeMillis()
        if (msg == lastError && now - lastErrorAt < 2000) return
        lastError = msg
        lastErrorAt = now
        onLog("脚本出错：$msg")
        onError?.invoke(msg)
    }

    private fun toV8(rt: V8Runtime, value: Any?): V8Value = when (value) {
        null, Unit -> rt.createV8ValueUndefined()
        is JsJson -> rt.globalObject.builtInJson.use { it.invoke<V8Value>("parse", value.text) }
        else -> rt.converter.toV8Value(rt, value)
    }

    /** A host failure becomes a JS Error with the same message, so scripts can catch it. */
    private fun hostCall(rt: V8Runtime, body: () -> Any?): V8Value = host {
        try {
            toV8(rt, body())
        } catch (e: Exception) {
            rt.throwError(V8ValueErrorType.Error, e.message ?: e.javaClass.simpleName)
            rt.createV8ValueUndefined()
        }
    }

    private inner class Scope(private val rt: V8Runtime) : JsScope {
        override fun define(name: String, build: JsObject.() -> Unit) {
            val spec = JsObject().apply(build)
            rt.createV8ValueObject().use { obj ->
                for ((key, value) in spec.values) toV8(rt, value).use { obj.set(key, it) }
                for ((key, body) in spec.functions) {
                    obj.bindFunction(
                        JavetCallbackContext(
                            key,
                            JavetCallbackType.DirectCallNoThisAndResult,
                            IJavetDirectCallable.NoThisAndResult<Exception> { args ->
                                hostCall(rt) { body(Args(rt, args ?: emptyArray())) }
                            },
                        ),
                    )
                }
                for ((key, body) in spec.getters) {
                    obj.bindProperty(
                        JavetCallbackContext(
                            key,
                            JavetCallbackType.DirectCallGetterAndNoThis,
                            IJavetDirectCallable.GetterAndNoThis<Exception> { hostCall(rt) { body() } },
                        ),
                    )
                }
                rt.globalObject.set(name, obj)
            }
        }
    }

    private class Args(private val rt: V8Runtime, private val values: Array<out V8Value>) : JsArgs {
        override val size: Int get() = values.size

        override fun string(i: Int): String {
            val v = values.getOrNull(i) ?: return ""
            if (v is V8ValueString) return v.value
            return rt.globalObject.invoke<V8Value>("String", v).use { (it as V8ValueString).value }
        }

        override fun number(i: Int): Double {
            val v = values.getOrNull(i) ?: return Double.NaN
            return rt.globalObject.invoke<V8Value>("Number", v).use {
                (rt.converter.toObject<Any?>(it) as? Number)?.toDouble() ?: Double.NaN
            }
        }

        override fun bool(i: Int): Boolean {
            val v = values.getOrNull(i) ?: return false
            if (v is V8ValueBoolean) return v.value
            return rt.globalObject.invoke<V8Value>("Boolean", v).use { (it as V8ValueBoolean).value }
        }

        override fun json(i: Int): String? {
            val v = values.getOrNull(i) ?: return null
            if (v is V8ValueUndefined || v is V8ValueNull) return null
            if (v is V8ValueString) return v.value
            return rt.globalObject.builtInJson.use { it.stringify(v) }
        }
    }

    private class ScriptException(message: String, cause: Throwable) : RuntimeException(message, cause)

    companion object {
        const val STUCK_MS = 5_000L
        private const val WATCH_MS = 100L
        private const val RESOURCE = "script.js"

        /** Same call as http.request. Models write fetch(); without this they report that scripts have no network. */
        private val FETCH = """
            function fetch(url, init) {
              var spec = { url: String(url == null ? "" : url) };
              if (init && typeof init === "object") {
                if (init.method) spec.method = init.method;
                if (init.headers) spec.headers = init.headers;
                if (init.body != null) spec.body = typeof init.body === "string" ? init.body : JSON.stringify(init.body);
                if (init.timeoutMs != null) spec.timeoutMs = init.timeoutMs;
              }
              var res = http.request(spec);
              return {
                ok: res.status >= 200 && res.status < 300,
                status: res.status,
                headers: res.headers || {},
                body: res.body || "",
                error: res.error || "",
                text: function () { return res.body || ""; },
                json: function () { return JSON.parse(res.body || ""); },
              };
            }
        """.trimIndent()
    }
}

/** A host capability hung on the container. Drawing plugins override [setDrawing]. */
interface JsPlugin {
    fun install(scope: JsScope)
    fun beforeSwap() {}
    fun afterSwap(ok: Boolean, pumpsFrames: Boolean) {}
    fun afterTurn() {}
    fun setDrawing(enabled: Boolean) {}

    /** True when the running script declares `onWallpaper`. A failed load does not call this. */
    fun wallpaperHook(enabled: Boolean) {}

    /** Bookends one [JsContainer.enterWallpaper] call. Default no-op. */
    fun beforeWallpaper() {}
    fun afterWallpaper() {}
}

/** Where plugins hang their globals. Engine types stay inside [JsContainer]. */
interface JsScope {
    fun define(name: String, build: JsObject.() -> Unit)
}

/**
 * One global object. Function bodies run on the script thread and may block it.
 * Return null or Unit for undefined, a String, Number, Boolean, Map, List, or [JsJson].
 */
class JsObject {
    internal val functions = LinkedHashMap<String, (JsArgs) -> Any?>()
    internal val getters = LinkedHashMap<String, () -> Any?>()
    internal val values = LinkedHashMap<String, Any?>()

    fun fn(name: String, body: (JsArgs) -> Any?) {
        functions[name] = body
    }

    fun getter(name: String, body: () -> Any?) {
        getters[name] = body
    }

    fun value(name: String, value: Any?) {
        values[name] = value
    }
}

/** Arguments as JS would coerce them. Missing ones read as "", NaN, false, or null. */
interface JsArgs {
    val size: Int
    fun string(i: Int): String
    fun number(i: Int): Double
    fun bool(i: Int): Boolean

    /** A string argument as given; anything else through `JSON.stringify`. Null for undefined or null. */
    fun json(i: Int): String?
}

/** JSON text that reaches the script as a parsed value. */
class JsJson(val text: String)
