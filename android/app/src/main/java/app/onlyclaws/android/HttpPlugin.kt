package app.onlyclaws.android

import org.json.JSONArray
import org.json.JSONObject
import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.NativeJSON
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined

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

    override fun install(cx: JsContext, scope: Scriptable) {
        val api = Api()
        api.parentScope = scope
        ScriptableObject.putProperty(scope, "http", api)
    }

    private fun request(cx: JsContext, scope: Scriptable, arg: Any?): Scriptable {
        val spec = readSpec(cx, scope, arg)
        val outcome = if (spec.error.isNotEmpty()) {
            HttpOutcome(0, "", spec.error, emptyMap())
        } else {
            call.perform(spec.spec)
        }
        return reply(cx, scope, outcome)
    }

    private fun reply(cx: JsContext, scope: Scriptable, outcome: HttpOutcome): Scriptable {
        val obj = cx.newObject(scope)
        ScriptableObject.putProperty(obj, "status", outcome.status)
        ScriptableObject.putProperty(obj, "body", outcome.body)
        ScriptableObject.putProperty(obj, "error", outcome.error)
        val headers = cx.newObject(scope)
        for ((name, value) in outcome.headers) {
            ScriptableObject.putProperty(headers, name, value)
        }
        ScriptableObject.putProperty(obj, "headers", headers)
        return obj
    }

    private inner class Api : ScriptableObject() {
        override fun getClassName(): String = "http"

        override fun get(name: String, start: Scriptable?): Any = when (name) {
            "request" -> requestFn
            else -> NOT_FOUND
        }

        private val requestFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                return request(cx, scope, args?.firstOrNull())
            }
        }
    }
}

private data class SpecRead(val spec: HttpSpec, val error: String)

private fun readSpec(cx: JsContext, scope: Scriptable, arg: Any?): SpecRead {
    val json = when (arg) {
        null, is Undefined -> null
        is String -> runCatching { JSONObject(arg) }.getOrNull()
        is JSONObject -> arg
        else -> runCatching {
            val text = NativeJSON.stringify(cx, scope, arg, null, null) as? String ?: return SpecRead(HttpSpec(""), "缺少 url")
            JSONObject(text)
        }.getOrNull()
    } ?: return SpecRead(HttpSpec(""), "缺少 url")

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
