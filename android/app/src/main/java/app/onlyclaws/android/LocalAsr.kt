package app.onlyclaws.android

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.OfflineSenseVoiceModelConfig
import java.io.File
import java.util.concurrent.Executors

/**
 * Speech to text on the phone with SenseVoice (sherpa-onnx). Nothing leaves the device.
 * The model sits in the app's files dir under `asr/sv/`. Hold to record; while
 * held, the audio so far is decoded every [TICK_MS] for a preview; release decodes it all.
 * Callbacks arrive on the main thread.
 */
class LocalAsr(private val context: Context) {
    private val main = Handler(Looper.getMainLooper())
    private val decoder = Executors.newSingleThreadExecutor { r -> Thread(r, "oca-asr").apply { isDaemon = true } }
    @Volatile private var recognizer: OfflineRecognizer? = null
    @Volatile private var loadError = ""
    private var loading = false
    private var take: Take? = null

    val modelDir: File get() = File(context.filesDir, "asr/sv")

    val ready: Boolean get() = recognizer != null

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
                        language = "zh",
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

    /** Starts recording. Returns false when the model is not loaded yet. */
    fun start(onPartial: (String) -> Unit, onFinal: (String) -> Unit, onError: (String) -> Unit): Boolean {
        if (recognizer == null || take != null) return false
        val t = Take(onPartial, onFinal, onError)
        take = t
        Thread({ record(t) }, "oca-asr-rec").start()
        main.postDelayed(tick, TICK_MS)
        return true
    }

    /** Stops recording after a short tail so the last syllable is kept; the final text follows. */
    fun stop() {
        val t = take ?: return
        if (!t.recording) return
        t.tailUntil = SystemClock.elapsedRealtime() + TAIL_MS
        t.recording = false
    }

    private fun record(t: Take) {
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
        decoder.execute {
            val text = decode(t.snapshot())
            main.post {
                if (take === t) take = null
                t.onFinal(text)
            }
        }
    }

    private fun fail(t: Take, message: String) {
        main.post {
            if (take === t) take = null
            t.onError(message)
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
        val r = recognizer ?: return ""
        val s = r.createStream()
        try {
            s.acceptWaveform(audio, SR)
            r.decode(s)
            return r.getResult(s).text.trim()
        } finally {
            s.release()
        }
    }

    private class Take(
        val onPartial: (String) -> Unit,
        val onFinal: (String) -> Unit,
        val onError: (String) -> Unit,
    ) {
        private val chunks = ArrayList<FloatArray>()
        @Volatile var size = 0
            private set
        @Volatile var recording = true
        @Volatile var tailUntil = 0L
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
    }

    companion object {
        private const val SR = 16000
        private const val CHUNK = 800
        private const val THREADS = 4
        private const val TICK_MS = 300L
        private const val TAIL_MS = 150L
        private const val MODEL = "model.int8.onnx"
        private const val TOKENS = "tokens.txt"
    }
}
