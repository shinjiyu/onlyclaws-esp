package app.onlyclaws.android

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Speech is a call, not a frame. `tts.say(text)` returns immediately;
 * when the utterance ends the shell calls `onDone` on the container thread.
 * While speaking, the script microphone is shut so the pet cannot hear itself.
 */
class TtsPlugin(
    private val app: Context,
    private val container: JsContainer,
    private val asr: LocalAsr,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    private val ready = AtomicBoolean(false)
    private val speaking = AtomicBoolean(false)
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
            override fun onStart(utteranceId: String?) {
                if (utteranceId != lastId) return
                speaking.set(true)
                asr.hushScript()
            }
            override fun onDone(utteranceId: String?) {
                if (utteranceId != lastId) return
                finished()
                container.fire("onDone")
            }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                if (utteranceId != lastId) return
                finished()
                onLog("朗读失败")
                container.fire("onDone")
            }
        })
        ready.set(true)
        while (pending.isNotEmpty()) sayNow(pending.removeFirst())
    }

    override fun install(scope: JsScope) = scope.define("tts") {
        getter("speaking") { speaking.get() }
        fn("say") { args ->
            val text = args.string(0)
            require(text.isNotEmpty()) { "tts.say(text)" }
            say(text)
        }
        fn("stop") { stop() }
    }

    override fun beforeSwap() {
        engine?.stop()
        pending.clear()
        finished(holdMs = 0)
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
        speaking.set(true)
        asr.hushScript()
        engine?.speak(text, TextToSpeech.QUEUE_FLUSH, Bundle(), id)
    }

    fun interrupt() {
        val was = speaking.get()
        pending.clear()
        engine?.stop()
        finished(holdMs = BARGE_HOLD_MS)
        if (was) container.fire("onDone")
    }

    private fun stop() {
        pending.clear()
        engine?.stop()
        finished(holdMs = BARGE_HOLD_MS)
    }

    private fun finished(holdMs: Long = ECHO_HOLD_MS) {
        speaking.set(false)
        asr.echoHold(holdMs)
    }

    companion object {
        private const val ECHO_HOLD_MS = 900L
        private const val BARGE_HOLD_MS = 400L
    }
}
