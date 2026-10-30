package app.onlyclaws.android

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

/**
 * The strip under every script. Typed or spoken text goes to the harness.
 * Speech uses the phone's own recognizer; phones without one fall back to typing.
 */
class HarnessBar(private val activity: AppCompatActivity, private val harness: Harness) {
    private val status = activity.findViewById<TextView>(R.id.harness_status)
    private val input = activity.findViewById<EditText>(R.id.harness_input)
    private val mic = activity.findViewById<Button>(R.id.harness_mic)
    private val send = activity.findViewById<Button>(R.id.harness_send)
    private var recognizer: SpeechRecognizer? = null
    private var listening = false
    private val show: (HarnessState) -> Unit = { state ->
        status.text = state.text
        send.isEnabled = !state.working
        send.alpha = if (state.working) 0.5f else 1f
    }

    fun attach() {
        send.setOnClickListener { submit() }
        input.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_SEND || action == EditorInfo.IME_ACTION_DONE) {
                submit()
                true
            } else {
                false
            }
        }
        mic.setOnClickListener { toggleListening() }
        harness.watch(show)
    }

    fun detach() {
        harness.unwatch(show)
        recognizer?.destroy()
        recognizer = null
    }

    /** Called from the activity once the microphone permission comes back. */
    fun onPermission(granted: Boolean) {
        if (granted) startListening() else status.text = "没有麦克风权限，先打字"
    }

    private fun submit() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        input.setText("")
        activity.getSystemService(InputMethodManager::class.java)
            ?.hideSoftInputFromWindow(input.windowToken, 0)
        harness.ask(text)
    }

    private fun toggleListening() {
        if (listening) {
            recognizer?.stopListening()
            return
        }
        if (!SpeechRecognizer.isRecognitionAvailable(activity)) {
            status.text = "这台手机没有系统语音识别，先打字"
            return
        }
        if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(activity, arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_MIC)
            return
        }
        startListening()
    }

    private fun startListening() {
        val engine = recognizer ?: SpeechRecognizer.createSpeechRecognizer(activity).also {
            it.setRecognitionListener(Listener())
            recognizer = it
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        setListening(true)
        engine.startListening(intent)
    }

    private fun setListening(on: Boolean) {
        listening = on
        mic.setText(if (on) R.string.harness_listening else R.string.harness_mic)
        if (on) status.text = "在听…"
    }

    private inner class Listener : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {}
        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {}
        override fun onEvent(eventType: Int, params: Bundle?) {}

        override fun onPartialResults(partialResults: Bundle?) {
            best(partialResults)?.let { input.setText(it) }
        }

        override fun onResults(results: Bundle?) {
            setListening(false)
            val text = best(results)
            if (text.isNullOrBlank()) {
                status.text = "没听清，再说一次"
                return
            }
            input.setText(text)
            submit()
        }

        override fun onError(error: Int) {
            setListening(false)
            status.text = when (error) {
                SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "没听清，再说一次"
                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "没有麦克风权限，先打字"
                SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "语音识别连不上网"
                else -> "语音识别出错（$error），先打字"
            }
        }

        private fun best(bundle: Bundle?): String? =
            bundle?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
    }

    companion object {
        const val REQUEST_MIC = 2
    }
}
