package app.onlyclaws.android

import org.json.JSONArray
import org.json.JSONObject

/**
 * Pull OCA preset scripts from the public OnlyClaws catalog (ADR 0009 / 0010).
 * No device token: list and source are public HTTPS GETs.
 */
class PresetCatalog(
    private val http: HttpCall = HttpCall(HttpCall.client()),
) {
    data class Item(
        val id: String,
        val title: String,
        val summary: String,
        val bytes: Int,
        val filename: String,
    )

    fun listOca(): Result<List<Item>> {
        val outcome = http.perform(HttpSpec(url = OcCloud.presetsListUrl("oca")))
        if (outcome.error.isNotEmpty()) return Result.failure(IllegalStateException(outcome.error))
        if (outcome.status !in 200..299) {
            return Result.failure(IllegalStateException("列表失败 ${outcome.status}"))
        }
        return runCatching { parseList(outcome.body) }
    }

    fun download(id: String): Result<String> {
        val clean = id.trim().lowercase()
        if (clean.isEmpty()) return Result.failure(IllegalArgumentException("缺少 id"))
        val outcome = http.perform(HttpSpec(url = OcCloud.presetSourceUrl(clean)))
        if (outcome.error.isNotEmpty()) return Result.failure(IllegalStateException(outcome.error))
        if (outcome.status !in 200..299) {
            return Result.failure(IllegalStateException("下载失败 ${outcome.status}"))
        }
        if (outcome.body.isBlank()) return Result.failure(IllegalStateException("脚本为空"))
        return Result.success(outcome.body)
    }

    companion object {
        fun parseList(body: String): List<Item> {
            val root = JSONObject(body)
            val arr = root.optJSONArray("presets") ?: JSONArray()
            val out = ArrayList<Item>(arr.length())
            for (i in 0 until arr.length()) {
                val p = arr.optJSONObject(i) ?: continue
                if (p.optString("kind") != "oca") continue
                val id = p.optString("id").trim()
                if (id.isEmpty()) continue
                out += Item(
                    id = id,
                    title = localized(p.opt("title")),
                    summary = localized(p.opt("summary")),
                    bytes = p.optInt("bytes"),
                    filename = p.optString("filename"),
                )
            }
            return out
        }

        fun localized(raw: Any?): String = when (raw) {
            is JSONObject -> raw.optString("zh").ifBlank { raw.optString("en") }
            is String -> raw
            else -> ""
        }
    }
}
