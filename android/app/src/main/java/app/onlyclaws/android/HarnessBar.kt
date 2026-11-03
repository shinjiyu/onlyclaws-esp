package app.onlyclaws.android

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
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
 * Hold 说 to talk; speech is recognized on the phone ([LocalAsr]) and sent on release.
 */
class HarnessBar(
    private val activity: AppCompatActivity,
    private val harness: Harness,
    private val asr: LocalAsr,
) {
    private val status = activity.findViewById<TextView>(R.id.harness_status)
    private val input = activity.findViewById<EditText>(R.id.harness_input)
    private val mic = activity.findViewById<Button>(R.id.harness_mic)
    private val send = activity.findViewById<Button>(R.id.harness_send)
    private var listening = false
    private val show: (HarnessState) -> Unit = { state ->
        status.text = state.text
        send.isEnabled = !state.working
        send.alpha = if (state.working) 0.5f else 1f
    }

    @SuppressLint("ClickableViewAccessibility")
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
        mic.setOnTouchListener { v, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                    startListening()
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> stopListening()
            }
            true
        }
        harness.watch(show)
        asr.warm { error -> if (error != null) status.text = error }
    }

    fun detach() {
        harness.unwatch(show)
        stopListening()
    }

    /** Called from the activity once the microphone permission comes back. */
    fun onPermission(granted: Boolean) {
        status.text = if (granted) "可以了，按住「说」讲话" else "没有麦克风权限，先打字"
    }

    private fun submit() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        input.setText("")
        activity.getSystemService(InputMethodManager::class.java)
            ?.hideSoftInputFromWindow(input.windowToken, 0)
        harness.ask(text)
    }

    private fun startListening() {
        if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(activity, arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_MIC)
            return
        }
        if (!asr.ready) {
            status.text = "语音模型还在加载，稍等"
            asr.warm { error -> status.text = error ?: "语音模型好了，再按住说" }
            return
        }
        val started = asr.start(
            owner = AsrOwner.Chat,
            onPartial = { input.setText(it) },
            onFinal = { text ->
                setListening(false)
                if (AsrText.filler(text)) {
                    input.setText("")
                    status.text = "没听清，再说一次"
                    return@start
                }
                input.setText(text)
                submit()
            },
            onError = { message ->
                setListening(false)
                status.text = message
            },
        )
        if (started) setListening(true)
    }

    private fun stopListening() {
        if (!listening) return
        asr.stop(AsrOwner.Chat)
        mic.setText(R.string.harness_mic)
        status.text = "识别中…"
    }

    private fun setListening(on: Boolean) {
        listening = on
        mic.setText(if (on) R.string.harness_listening else R.string.harness_mic)
        if (on) status.text = "在听…松开发送"
    }

    companion object {
        const val REQUEST_MIC = 2
    }
}
