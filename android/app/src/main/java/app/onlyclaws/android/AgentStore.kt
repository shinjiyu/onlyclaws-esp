package app.onlyclaws.android

import org.json.JSONObject
import java.io.File

/** pi-ai credentials and the current model, next to the script files. */
class AgentStore(private val root: File) {
    private val dir = File(root, "agent").apply { mkdirs() }
    private val authFile = File(dir, "auth.json")
    private val settingsFile = File(dir, "settings.json")

    data class Settings(
        val provider: String = "deepseek",
        val model: String = "deepseek-flash",
        val custom: Custom? = null,
    )

    data class Custom(
        val id: String = "custom",
        val name: String = "自定义",
        val baseUrl: String = "",
        val api: String = "openai-completions",
        val model: String = "",
        val contextWindow: Int = 128000,
        val maxTokens: Int = 8192,
    )

    init {
        migrateOldKey()
    }

    fun settings(): Settings {
        if (!settingsFile.exists()) return Settings()
        val obj = runCatching { JSONObject(settingsFile.readText()) }.getOrNull() ?: return Settings()
        val custom = obj.optJSONObject("custom")?.let {
            Custom(
                id = it.optString("id", "custom"),
                name = it.optString("name", "自定义"),
                baseUrl = it.optString("baseUrl"),
                api = it.optString("api", "openai-completions"),
                model = it.optString("model"),
                contextWindow = it.optInt("contextWindow", 128000),
                maxTokens = it.optInt("maxTokens", 8192),
            ).takeIf { c -> c.baseUrl.isNotBlank() && c.model.isNotBlank() }
        }
        return Settings(
            provider = obj.optString("provider", "deepseek").ifBlank { "deepseek" },
            model = obj.optString("model", "deepseek-flash").ifBlank { "deepseek-flash" },
            custom = custom,
        )
    }

    fun writeSettings(settings: Settings) {
        val obj = JSONObject()
            .put("provider", settings.provider)
            .put("model", settings.model)
        settings.custom?.let { c ->
            obj.put(
                "custom",
                JSONObject()
                    .put("id", c.id)
                    .put("name", c.name)
                    .put("baseUrl", c.baseUrl)
                    .put("api", c.api)
                    .put("model", c.model)
                    .put("contextWindow", c.contextWindow)
                    .put("maxTokens", c.maxTokens),
            )
        }
        settingsFile.writeText(obj.toString())
    }

    fun key(provider: String): String {
        val obj = auth()
        val cred = obj.optJSONObject(provider) ?: return ""
        return cred.optString("key")
    }

    fun writeKey(provider: String, key: String) {
        val obj = auth()
        if (key.isBlank()) {
            obj.remove(provider)
        } else {
            obj.put(provider, JSONObject().put("type", "api_key").put("key", key))
        }
        authFile.writeText(obj.toString())
    }

    fun providersWithKeys(): List<String> {
        val obj = auth()
        return obj.keys().asSequence().filter { obj.optJSONObject(it)?.optString("key").orEmpty().isNotBlank() }.toList()
    }

    fun settingsJson(): String {
        val s = settings()
        val obj = JSONObject().put("provider", s.provider).put("model", s.model)
        s.custom?.let { c ->
            obj.put(
                "custom",
                JSONObject()
                    .put("id", c.id)
                    .put("name", c.name)
                    .put("baseUrl", c.baseUrl)
                    .put("api", c.api)
                    .put("model", c.model)
                    .put("contextWindow", c.contextWindow)
                    .put("maxTokens", c.maxTokens),
            )
        }
        return obj.toString()
    }

    private fun auth(): JSONObject =
        if (authFile.exists()) runCatching { JSONObject(authFile.readText()) }.getOrDefault(JSONObject()) else JSONObject()

    /** The old harness kept one DeepSeek key in files/keys/deepseek. */
    private fun migrateOldKey() {
        if (key("deepseek").isNotEmpty()) return
        val old = File(File(root, "keys"), "deepseek")
        val text = old.takeIf { it.isFile }?.readText()?.trim().orEmpty()
        if (text.startsWith("sk-")) writeKey("deepseek", text)
    }
}
