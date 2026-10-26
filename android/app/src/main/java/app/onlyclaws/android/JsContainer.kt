package app.onlyclaws.android

import android.content.Context
import android.os.Handler
import android.os.HandlerThread
import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * One JS engine thread. Plugins install host objects; the shell calls in.
 * A failed load leaves the previous script in place.
 */
class JsContainer(private val onLog: (String) -> Unit) {
    private val thread = HandlerThread("oca-js").apply { start() }
    private val handler = Handler(thread.looper)
    private val plugins = mutableListOf<JsPlugin>()
    private val frameBusy = AtomicBoolean(false)
    private var scope: Scriptable? = null
    private var lastError = ""
    private var lastErrorAt = 0L

    fun use(plugin: JsPlugin) {
        plugins += plugin
    }

    fun load(source: String, done: (Result<Unit>) -> Unit) {
        handler.post {
            plugins.forEach { it.beforeSwap() }
            var pumps = false
            val result = runCatching { pumps = swap(source) }
            plugins.forEach { it.afterSwap(result.isSuccess, pumps) }
            plugins.forEach { it.afterTurn() }
            done(result)
        }
    }

    /** Pointer and other host events. Serialized behind whatever the engine is already doing. */
    fun enter(block: (JsContext, Scriptable) -> Unit) {
        handler.post {
            val current = scope ?: return@post
            val cx = JsContext.enter()
            try {
                block(cx, current)
            } catch (t: Throwable) {
                noteError(t)
            } finally {
                JsContext.exit()
            }
            plugins.forEach { it.afterTurn() }
        }
    }

    /** One vsync. Extra frames are dropped until this one returns. */
    fun enterFrame(dt: Double) {
        if (!frameBusy.compareAndSet(false, true)) return
        handler.post {
            try {
                val current = scope ?: return@post
                val cx = JsContext.enter()
                try {
                    call(cx, current, "onFrame", arrayOf(dt))
                } catch (t: Throwable) {
                    noteError(t)
                } finally {
                    JsContext.exit()
                }
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

    private fun swap(source: String): Boolean {
        val cx = JsContext.enter()
        try {
            cx.optimizationLevel = -1
            val fresh = cx.initStandardObjects()
            ScriptableObject.putProperty(fresh, "oca", OcaLog(onLog))
            plugins.forEach { it.install(cx, fresh) }
            cx.evaluateString(fresh, source, "script.js", 1, null)
            call(cx, fresh, "onStart")
            val pumps = fresh.get("onFrame", fresh) is BaseFunction
            val previous = scope
            scope = fresh
            plugins.forEach { it.setDrawing(false) }
            try {
                if (previous != null) call(cx, previous, "onStop")
            } catch (t: Throwable) {
                noteError(t)
            } finally {
                plugins.forEach { it.setDrawing(true) }
            }
            return pumps
        } finally {
            JsContext.exit()
        }
    }

    private fun call(cx: JsContext, scope: Scriptable, name: String, args: Array<Any?> = emptyArray()) {
        val fn = scope.get(name, scope)
        if (fn is BaseFunction) fn.call(cx, scope, scope, args)
    }

    private fun noteError(t: Throwable) {
        val msg = t.message?.lineSequence()?.firstOrNull().orEmpty()
        val now = System.currentTimeMillis()
        if (msg == lastError && now - lastErrorAt < 2000) return
        lastError = msg
        lastErrorAt = now
        onLog("脚本出错：$msg")
    }

    private class OcaLog(private val emit: (String) -> Unit) : ScriptableObject() {
        override fun getClassName(): String = "oca"

        override fun get(name: String, start: Scriptable?): Any {
            if (name == "log") return logFn
            return NOT_FOUND
        }

        private val logFn = object : BaseFunction() {
            override fun call(
                cx: JsContext,
                scope: Scriptable,
                thisObj: Scriptable,
                args: Array<out Any>?,
            ): Any {
                emit(args?.firstOrNull()?.toString().orEmpty())
                return Undefined.instance
            }
        }
    }
}

/** A host capability hung on the container. Drawing plugins override [setDrawing]. */
interface JsPlugin {
    fun install(cx: JsContext, scope: Scriptable)
    fun beforeSwap() {}
    fun afterSwap(ok: Boolean, pumpsFrames: Boolean) {}
    fun afterTurn() {}
    fun setDrawing(enabled: Boolean) {}
}
