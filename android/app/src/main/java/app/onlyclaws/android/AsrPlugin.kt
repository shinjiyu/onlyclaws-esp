package app.onlyclaws.android

/**
 * One microphone, same [LocalAsr] the chat ball uses.
 *
 *   asr.warm()
 *   asr.ready / asr.hasModel / asr.listening
 *   asr.start()  // hold
 *   asr.stop()   // release; then onSpeech({ text, partial: false })
 *
 * Partial previews call `onSpeech({ text, partial: true })`.
 * Errors call `onSpeech({ text: "", partial: false, error })`.
 */
class AsrPlugin(
    private val asr: LocalAsr,
    private val container: JsContainer,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    override fun install(scope: JsScope) = scope.define("asr") {
        getter("ready") { asr.ready }
        getter("hasModel") { asr.hasModel() }
        getter("listening") { asr.listening(AsrOwner.Script) }
        getter("holder") { asr.holder }
        getter("deaf") { asr.deaf }
        fn("warm") {
            asr.warm { error ->
                if (error != null) {
                    onLog(error)
                    container.fire("onSpeech", mapOf("text" to "", "partial" to false, "error" to error))
                }
            }
        }
        fn("start") { start() }
        fn("stop") { asr.stop(AsrOwner.Script) }
    }

    override fun beforeSwap() {
        if (asr.listening(AsrOwner.Script)) asr.stop(AsrOwner.Script)
    }

    private fun start(): Boolean {
        if (!asr.ready) {
            asr.warm { error ->
                if (error != null) {
                    onLog(error)
                    container.fire("onSpeech", mapOf("text" to "", "partial" to false, "error" to error))
                }
            }
            return false
        }
        return asr.start(
            owner = AsrOwner.Script,
            onPartial = { text ->
                container.fire("onSpeech", mapOf("text" to text, "partial" to true))
            },
            onFinal = { text ->
                container.fire("onSpeech", mapOf("text" to text, "partial" to false))
            },
            onError = { message ->
                onLog(message)
                container.fire("onSpeech", mapOf("text" to "", "partial" to false, "error" to message))
            },
        )
    }
}
