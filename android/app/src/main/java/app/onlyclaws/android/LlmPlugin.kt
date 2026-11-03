package app.onlyclaws.android

/**
 * Script-side chat. Uses the same [AgentStore] key the agent uses.
 *
 *   llm.ready / llm.provider / llm.model
 *   llm.chat({ messages: [{ role, content, image? }], system? })
 *     → { text, error, provider, model }
 */
class LlmPlugin(
    private val store: AgentStore,
    private val chat: LlmChat = LlmChat(),
) : JsPlugin {
    override fun install(scope: JsScope) = scope.define("llm") {
        getter("ready") { ready() }
        getter("provider") { store.settings().provider }
        getter("model") {
            val s = store.settings()
            if (LlmEndpoints.usingCustom(s)) s.custom?.model?.ifBlank { s.model } ?: s.model else s.model
        }
        fn("chat") { chat.complete(store, it.json(0)) }
    }

    private fun ready(): Boolean {
        val settings = store.settings()
        val name = if (LlmEndpoints.usingCustom(settings)) {
            settings.custom?.id?.ifBlank { "custom" } ?: "custom"
        } else {
            settings.provider
        }
        return store.key(name).isNotEmpty() && LlmEndpoints.chatUrl(settings).isNotEmpty()
    }
}
