package app.onlyclaws.android

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined
import java.util.Locale
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Speech is a call, not a frame. `tts.say(text)` returns immediately;
 * when the utterance ends the shell calls `onDone` on the container thread.
 */
class TtsPlugin(
    private val app: Context,
    private val container: JsContainer,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    private val ready = AtomicBoolean(false)
    private var engine: TextToSpeech? = null
    private var lastId = ""
    private val pending = ArrayDeque<String>()
    private val candidates: MutableList<String?> = ArrayList()
    private var attempt = 0

    init {
        val found = app.packageManager
            .queryIntentServices(Intent(TextToSpeech.Engine.INTENT_ACTION_TTS_SERVICE), 0)
            .map { it.serviceInfo.packageName }
            .distinct()
        candidates += found
        for (extra in listOf("com.oplus.ttsaccessibilityengine", "com.google.android.tts")) {
            if (extra !in candidates) candidates += extra
        }
        candidates += null
        if (found.isNotEmpty()) onLog("朗读引擎 ${found.joinToString()}")
        openNext()
    }

    private fun openNext() {
        if (attempt >= candidates.size) {
            onLog("朗读引擎不可用")
            return
        }
        val name = candidates[attempt++]
        runCatching { engine?.shutdown() }
        engine = null
        engine = try {
            if (name == null) TextToSpeech(app, ::onInit) else TextToSpeech(app, ::onInit, name)
        } catch (_: Throwable) {
            openNext()
            return
        }
    }

    private fun onInit(status: Int) {
        if (status != TextToSpeech.SUCCESS) {
            openNext()
            return
        }
        val tts = engine ?: return
        val locales = listOf(Locale.SIMPLIFIED_CHINESE, Locale.CHINA, Locale.CHINESE, Locale.getDefault(), Locale.US)
        var ok = false
        for (locale in locales) {
            val result = tts.setLanguage(locale)
            if (result != TextToSpeech.LANG_MISSING_DATA && result != TextToSpeech.LANG_NOT_SUPPORTED) {
                ok = true
                break
            }
        }
        if (!ok) {
            openNext()
            return
        }
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) {
                if (utteranceId != lastId) return
                container.enter { cx, scope ->
                    val fn = scope.get("onDone", scope)
                    if (fn is BaseFunction) fn.call(cx, scope, scope, emptyArray())
                }
            }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                onLog("朗读失败")
            }
        })
        ready.set(true)
        while (pending.isNotEmpty()) sayNow(pending.removeFirst())
    }

    override fun install(cx: JsContext, scope: Scriptable) {
        val api = Api()
        api.parentScope = scope
        ScriptableObject.putProperty(scope, "tts", api)
    }

    override fun beforeSwap() {
        engine?.stop()
        pending.clear()
    }

    fun release() {
        pending.clear()
        engine?.stop()
        engine?.shutdown()
        engine = null
        ready.set(false)
    }

    private fun say(text: String) {
        if (!ready.get()) {
            pending.addLast(text)
            if (engine == null) openNext()
            return
        }
        sayNow(text)
    }

    private fun sayNow(text: String) {
        val id = UUID.randomUUID().toString()
        lastId = id
        engine?.speak(text, TextToSpeech.QUEUE_FLUSH, Bundle(), id)
    }

    private fun stop() {
        pending.clear()
        engine?.stop()
    }

    private inner class Api : ScriptableObject() {
        override fun getClassName(): String = "tts"

        override fun get(name: String, start: Scriptable?): Any = when (name) {
            "say" -> sayFn
            "stop" -> stopFn
            else -> NOT_FOUND
        }

        private val sayFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                val text = args?.firstOrNull()?.toString().orEmpty()
                if (text.isEmpty()) throw JsContext.reportRuntimeError("tts.say(text)")
                say(text)
                return Undefined.instance
            }
        }

        private val stopFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                stop()
                return Undefined.instance
            }
        }
    }
}
