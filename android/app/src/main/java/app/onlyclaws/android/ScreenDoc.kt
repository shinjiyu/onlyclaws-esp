package app.onlyclaws.android

import org.json.JSONObject

/**
 * Inline HTML for the main screen. The page cannot navigate or load the network.
 * A click on `[data-action]` becomes `onAction({ action, context })`.
 * `context` is the current `[data-field]` values, plus `value` from `data-value`.
 */
internal object ScreenDoc {
    const val MAX_CHARS = 512 * 1024
    const val ORIGIN = "https://screen.oca.invalid/"

    fun document(source: String): String {
        val body = source.trim()
        val bridge = "<script>$BRIDGE</script>"
        if (HTML.containsMatchIn(body)) return body + bridge
        return """
            <!DOCTYPE html>
            <html>
            <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
            html,body{margin:0;min-height:100%;background:#141210;color:#f4f1ea;font:16px/1.45 sans-serif}
            button,input,textarea{font:inherit}
            </style>
            </head>
            <body>$body$bridge</body>
            </html>
        """.trimIndent()
    }

    /** Null when the click should be ignored. Otherwise JSON for `onAction`. */
    fun event(action: String, contextJson: String?): String? {
        val name = action.trim()
        if (name.isEmpty() || name.length > 64) return null
        if (!name.all { it.isLetterOrDigit() || it == '_' || it == '-' }) return null
        val raw = runCatching { JSONObject(contextJson?.take(32_000) ?: "{}") }.getOrNull() ?: JSONObject()
        val context = JSONObject()
        var kept = 0
        for (key in raw.keys()) {
            if (kept >= 40 || key.isEmpty() || key.length > 64) continue
            val value = raw.get(key)
            context.put(
                key,
                when (value) {
                    is String -> value.take(4_000)
                    is Number, is Boolean -> value
                    JSONObject.NULL -> ""
                    else -> value.toString().take(4_000)
                },
            )
            kept++
        }
        return JSONObject().put("action", name).put("context", context).toString()
    }

    private val HTML = Regex("<html[\\s>]", RegexOption.IGNORE_CASE)

    private const val BRIDGE = """
(function(){
  function fields(){
    var ctx = {};
    var nodes = document.querySelectorAll("[data-field]");
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      var key = n.getAttribute("data-field");
      if (!key) continue;
      if (n.type === "checkbox") ctx[key] = !!n.checked;
      else ctx[key] = n.value != null ? String(n.value) : (n.textContent || "");
    }
    return ctx;
  }
  document.addEventListener("click", function(e){
    var t = e.target;
    var el = t && t.closest ? t.closest("[data-action]") : null;
    if (!el) return;
    e.preventDefault();
    var ctx = fields();
    var extra = el.getAttribute("data-value");
    if (extra != null) ctx.value = extra;
    if (window.OcaScreen && OcaScreen.action) OcaScreen.action(el.getAttribute("data-action") || "", JSON.stringify(ctx));
  }, true);
})();
"""
}
