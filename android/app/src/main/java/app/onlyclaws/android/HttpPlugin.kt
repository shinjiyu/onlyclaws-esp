package app.onlyclaws.android

import org.json.JSONArray
import org.json.JSONObject

/**
 * Blocking request on the script thread.
 *
 *   var res = http.request({ url, method, headers, body, timeoutMs })
 *   res.status    0 when nothing came back
 *   res.body
 *   res.error     empty when a status came back
 *   res.headers   names are lower case
 */
class HttpPlugin : JsPlugin {
    private val call = HttpCall(HttpCall.client())

    override fun install(scope: JsScope) = scope.define("http") {
        fn("request") { request(it.json(0)) }
    }

    private fun request(arg: String?): Map<String, Any> {
        val spec = readSpec(arg)
        val outcome = if (spec.error.isNotEmpty()) {
            HttpOutcome(0, "", spec.error, emptyMap())
        } else {
            call.perform(spec.spec)
        }
        return mapOf(
            "status" to outcome.status,
            "body" to outcome.body,
            "error" to outcome.error,
            "headers" to LinkedHashMap(outcome.headers),
        )
    }
}

private data class SpecRead(val spec: HttpSpec, val error: String)

private fun readSpec(arg: String?): SpecRead {
    val json = arg?.let { runCatching { JSONObject(it) }.getOrNull() }
        ?: return SpecRead(HttpSpec(""), "缺少 url")

    val headers = LinkedHashMap<String, String>()
    when (val raw = json.opt("headers")) {
        null, JSONObject.NULL -> {}
        is JSONObject -> {
            val keys = raw.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                val value = raw.opt(key)
                if (value !is String) return SpecRead(HttpSpec(""), "headers 无效")
                headers[key] = value
            }
        }
        else -> return SpecRead(HttpSpec(""), "headers 无效")
    }

    val body = when (val raw = json.opt("body")) {
        null, JSONObject.NULL -> null
        is String -> raw
        is JSONObject, is JSONArray -> raw.toString()
        else -> raw.toString()
    }
    val timeout = if (json.has("timeoutMs")) json.optLong("timeoutMs", 60_000) else 60_000
    return SpecRead(
        HttpSpec(
            url = json.optString("url"),
            method = json.optString("method", "GET"),
            headers = headers,
            body = body,
            timeoutMs = timeout,
        ),
        "",
    )
}
