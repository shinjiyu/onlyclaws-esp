package app.onlyclaws.android

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.OfflineSenseVoiceModelConfig
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.sqrt

enum class AsrOwner { Chat, Script }

/**
 * Speech to text on the phone with SenseVoice (sherpa-onnx). Nothing leaves the device.
 * The model sits in the app's files dir under `asr/sv/`. Hold to record; while
 * held, the audio so far is decoded every [TICK_MS] for a preview; release decodes it all.
 * Chat and the script share one microphone: chat can take it, the script cannot.
 * Callbacks arrive on the main thread.
 */
class LocalAsr(private val context: Context) {
    private val main = Handler(Looper.getMainLooper())
    private val decoder = Executors.newSingleThreadExecutor { r -> Thread(r, "oca-asr").apply { isDaemon = true } }
    @Volatile private var recognizer: OfflineRecognizer? = null
    @Volatile private var loadError = ""
    private var loading = false
    private var take: Take? = null
    @Volatile private var hushUntil = 0L
    var onBargeIn: (() -> Unit)? = null

    val modelDir: File get() = File(context.filesDir, "asr/sv")

    val ready: Boolean get() = recognizer != null

    val recording: Boolean get() = take?.recording == true

    val owner: AsrOwner? get() = take?.owner

    val holder: String
        get() = when (take?.owner) {
            AsrOwner.Chat -> "chat"
            AsrOwner.Script -> "script"
            null -> ""
        }

    fun listening(who: AsrOwner): Boolean = take?.let { it.owner == who && it.recording } == true

    val deaf: Boolean get() = SystemClock.elapsedRealtime() < hushUntil

    /** Drop script capture and ignore new script starts until [echoHold]. */
    fun hushScript() {
        drop(AsrOwner.Script)
        hushUntil = Long.MAX_VALUE
        Log.i(TAG, "hush script")
    }

    fun echoHold(ms: Long) {
        hushUntil = SystemClock.elapsedRealtime() + ms.coerceAtLeast(0)
        Log.i(TAG, "echo hold ${ms}ms")
    }

    private fun drop(who: AsrOwner) {
        val current = take ?: return
        if (current.owner != who) return
        current.cancelled = true
        current.recording = false
        current.tailUntil = 0L
        Log.i(TAG, "drop ${who.name}")
    }

    fun hasModel(): Boolean = File(modelDir, MODEL).isFile && File(modelDir, TOKENS).isFile

    /** Loads the model in the background once. [done] gets an error message, or null when ready. */
    fun warm(done: (String?) -> Unit) {
        if (recognizer != null) return done(null)
        if (!hasModel()) return done("语音模型没装（${modelDir.absolutePath}）")
        if (loading) return
        loading = true
        decoder.execute {
            val config = OfflineRecognizerConfig(
                featConfig = FeatureConfig(sampleRate = SR, featureDim = 80),
                modelConfig = OfflineModelConfig(
                    senseVoice = OfflineSenseVoiceModelConfig(
                        model = File(modelDir, MODEL).absolutePath,
                        language = "auto",
                        useInverseTextNormalization = true,
                    ),
                    tokens = File(modelDir, TOKENS).absolutePath,
                    numThreads = THREADS,
                    debug = false,
                    provider = "cpu",
                ),
            )
            val r = runCatching { OfflineRecognizer(config = config) }
                .onFailure { loadError = "语音模型加载失败：${it.message}" }
                .getOrNull()
            recognizer = r
            main.post {
                loading = false
                done(if (r == null) loadError else null)
            }
        }
    }

    /** Starts recording for [owner]. Chat can take the mic from the script. */
    fun start(
        owner: AsrOwner,
        onPartial: (String) -> Unit,
        onFinal: (String) -> Unit,
        onError: (String) -> Unit,
    ): Boolean {
        if (recognizer == null) return false
        if (owner == AsrOwner.Chat) onBargeIn?.invoke()
        if (owner == AsrOwner.Script && SystemClock.elapsedRealtime() < hushUntil) {
            Log.i(TAG, "start Script blocked (tts echo)")
            return false
        }
        val current = take
        if (current != null) {
            if (current.recording) {
                if (current.owner == owner) return true
                if (owner == AsrOwner.Script && current.owner == AsrOwner.Chat) return false
                current.abort("聊天在用麦克风")
            } else {
                current.cancelled = true
            }
            runCatching { current.released.await(400, TimeUnit.MILLISECONDS) }
            if (take === current) take = null
        }
        val t = Take(owner, onPartial, onFinal, onError)
        take = t
        Thread({ record(t) }, "oca-asr-rec").start()
        main.postDelayed(tick, TICK_MS)
        Log.i(TAG, "start ${owner.name}")
        return true
    }

    fun stop(owner: AsrOwner) {
        val t = take ?: return
        if (t.owner != owner) return
        if (!t.recording) return
        t.tailUntil = SystemClock.elapsedRealtime() + TAIL_MS
        t.recording = false
        Log.i(TAG, "stop ${owner.name} samples=${t.size}")
    }

    private fun record(t: Take) {
        try {
            val min = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            val rec = try {
                AudioRecord(
                    MediaRecorder.AudioSource.VOICE_RECOGNITION, SR, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, maxOf(min, CHUNK * 2) * 2,
                )
            } catch (_: SecurityException) {
                return fail(t, "没有麦克风权限")
            }
            if (rec.state != AudioRecord.STATE_INITIALIZED) {
                rec.release()
                return fail(t, "麦克风打不开")
            }
            val buf = ShortArray(CHUNK)
            rec.startRecording()
            try {
                while (t.recording || SystemClock.elapsedRealtime() < t.tailUntil) {
                    val n = rec.read(buf, 0, CHUNK)
                    if (n < 0) break
                    if (n == 0) continue
                    t.add(FloatArray(n) { buf[it] / 32768f })
                }
            } finally {
                rec.stop()
                rec.release()
            }
            if (t.cancelled) return
            decoder.execute {
                val snap = t.snapshot()
                val text = decode(snap)
                Log.i(TAG, "final ${t.owner.name} samples=${snap.size} rms=${rms(snap)} text=$text")
                main.post {
                    if (take === t) take = null
                    if (!t.cancelled) t.onFinal(text)
                }
            }
        } finally {
            t.released.countDown()
        }
    }

    private fun fail(t: Take, message: String) {
        Log.w(TAG, "fail ${t.owner.name} $message")
        main.post {
            if (take === t) take = null
            if (!t.cancelled) t.onError(message)
        }
    }

    private val tick = object : Runnable {
        override fun run() {
            val t = take ?: return
            if (!t.recording) return
            if (!t.previewBusy && t.size > t.previewed && t.size >= SR / 5) {
                t.previewBusy = true
                t.previewed = t.size
                decoder.execute {
                    val text = decode(t.snapshot())
                    main.post {
                        t.previewBusy = false
                        if (take === t && t.recording && text.isNotBlank()) t.onPartial(text)
                    }
                }
            }
            main.postDelayed(this, TICK_MS)
        }
    }

    private fun decode(audio: FloatArray): String {
        if (audio.size < SR / 4) return ""
        val r = recognizer ?: return ""
        val s = r.createStream()
        try {
            s.acceptWaveform(audio, SR)
            r.decode(s)
            return AsrText.clean(r.getResult(s).text)
        } finally {
            s.release()
        }
    }

    private class Take(
        val owner: AsrOwner,
        val onPartial: (String) -> Unit,
        val onFinal: (String) -> Unit,
        val onError: (String) -> Unit,
    ) {
        private val chunks = ArrayList<FloatArray>()
        val released = CountDownLatch(1)
        @Volatile var size = 0
            private set
        @Volatile var recording = true
        @Volatile var tailUntil = 0L
        @Volatile var cancelled = false
        var previewBusy = false
        var previewed = 0

        @Synchronized fun add(x: FloatArray) {
            chunks.add(x)
            size += x.size
        }

        @Synchronized fun snapshot(): FloatArray {
            val out = FloatArray(size)
            var o = 0
            for (c in chunks) {
                c.copyInto(out, o)
                o += c.size
            }
            return out
        }

        fun abort(message: String) {
            cancelled = true
            recording = false
            tailUntil = 0L
            Handler(Looper.getMainLooper()).post { onError(message) }
        }
    }

    companion object {
        private const val TAG = "OCA-ASR"
        private const val SR = 16000
        private const val CHUNK = 800
        private const val THREADS = 4
        private const val TICK_MS = 300L
        private const val TAIL_MS = 280L
        private const val MODEL = "model.int8.onnx"
        private const val TOKENS = "tokens.txt"

        private fun rms(audio: FloatArray): String {
            if (audio.isEmpty()) return "0"
            var s = 0.0
            for (x in audio) s += x * x
            return String.format("%.4f", sqrt(s / audio.size))
        }
    }
}
