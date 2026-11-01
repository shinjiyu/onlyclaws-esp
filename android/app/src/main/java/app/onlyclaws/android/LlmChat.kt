package app.onlyclaws.android

import org.json.JSONArray
import org.json.JSONObject

/**
 * OpenAI-compatible chat for scripts. The key stays in [AgentStore];
 * the script only sees `{ text, error, provider, model }`.
 */
class LlmChat(private val call: HttpCall = HttpCall(HttpCall.client())) {
    fun complete(store: AgentStore, specJson: String?): Map<String, Any> {
        val settings = store.settings()
        val provider = settings.provider
        val model = if (LlmEndpoints.usingCustom(settings)) {
            settings.custom?.model?.ifBlank { settings.model } ?: settings.model
        } else {
            settings.model
        }
        val keyName = if (LlmEndpoints.usingCustom(settings)) {
            settings.custom?.id?.ifBlank { "custom" } ?: "custom"
        } else {
            provider
        }
        val key = store.key(keyName)
        val url = LlmEndpoints.chatUrl(settings)
        if (url.isEmpty()) {
            return result("", "这个后端脚本走 OpenAI 兼容接口，请换 DeepSeek / OpenAI / 自定义", provider, model)
        }
        if (key.isEmpty()) {
            return result("", "还没有这个后端的 API key", provider, model)
        }
        val parsed = parse(specJson) ?: return result("", "llm.chat({ messages })", provider, model)
        val body = JSONObject()
            .put("model", model)
            .put("messages", parsed)
            .put("stream", false)
            .toString()
        val outcome = call.perform(
            HttpSpec(
                url = url,
                method = "POST",
                headers = mapOf(
                    "Authorization" to "Bearer $key",
                    "Content-Type" to "application/json",
                ),
                body = body,
                timeoutMs = 120_000,
            ),
        )
        if (outcome.status == 401) return result("", "API key 不对", provider, model)
        if (outcome.status != 200) {
            val detail = if (outcome.status == 0) outcome.error else "HTTP ${outcome.status} ${apiError(outcome.body)}"
            return result("", "模型没回：$detail".trim(), provider, model)
        }
        val text = readText(outcome.body)
        return if (text.isNullOrBlank()) result("", "模型回复读不出来", provider, model) else result(text, "", provider, model)
    }

    companion object {
        private const val MAX_MESSAGES = 40
        private const val MAX_CHARS = 8000

        fun parse(specJson: String?): JSONArray? {
            val obj = specJson?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return null
            val raw = obj.optJSONArray("messages") ?: return null
            if (raw.length() == 0) return null
            val out = JSONArray()
            obj.optString("system").trim().takeIf { it.isNotEmpty() }?.let { system ->
                out.put(JSONObject().put("role", "system").put("content", system.take(MAX_CHARS)))
            }
            val cap = minOf(raw.length(), MAX_MESSAGES)
            for (i in 0 until cap) {
                val item = raw.optJSONObject(i) ?: return null
                val role = item.optString("role").ifBlank { "user" }
                if (role !in ROLES) return null
                val content = item.optString("content").trim()
                if (content.isEmpty()) return null
                out.put(JSONObject().put("role", role).put("content", content.take(MAX_CHARS)))
            }
            return if (out.length() == 0) null else out
        }

        fun readText(body: String): String? =
            runCatching {
                JSONObject(body).getJSONArray("choices").getJSONObject(0)
                    .getJSONObject("message").getString("content")
            }.getOrNull()?.trim()

        private fun apiError(body: String): String =
            runCatching { JSONObject(body).getJSONObject("error").getString("message") }.getOrDefault("").take(120)

        private fun result(text: String, error: String, provider: String, model: String) = mapOf(
            "text" to text,
            "error" to error,
            "provider" to provider,
            "model" to model,
        )

        private val ROLES = setOf("system", "user", "assistant")
    }
}

object LlmEndpoints {
    fun usingCustom(settings: AgentStore.Settings): Boolean {
        val custom = settings.custom ?: return false
        val id = custom.id.ifBlank { "custom" }
        return settings.provider == id || settings.provider == "custom"
    }

    fun chatUrl(settings: AgentStore.Settings): String {
        if (usingCustom(settings)) {
            return settings.custom?.baseUrl?.trim()?.takeIf { it.isNotEmpty() }?.let { join(it) }.orEmpty()
        }
        return when (settings.provider) {
            "deepseek" -> "https://api.deepseek.com/v1/chat/completions"
            "openai" -> "https://api.openai.com/v1/chat/completions"
            "openrouter" -> "https://openrouter.ai/api/v1/chat/completions"
            "groq" -> "https://api.groq.com/openai/v1/chat/completions"
            "moonshotai" -> "https://api.moonshot.ai/v1/chat/completions"
            "moonshotai-cn" -> "https://api.moonshot.cn/v1/chat/completions"
            "xai" -> "https://api.x.ai/v1/chat/completions"
            "zai" -> "https://api.z.ai/api/paas/v4/chat/completions"
            "zai-coding-cn" -> "https://open.bigmodel.cn/api/paas/v4/chat/completions"
            else -> ""
        }
    }

    fun join(base: String): String {
        val trimmed = base.trim().trimEnd('/')
        return if (trimmed.endsWith("chat/completions")) trimmed else "$trimmed/chat/completions"
    }
}
