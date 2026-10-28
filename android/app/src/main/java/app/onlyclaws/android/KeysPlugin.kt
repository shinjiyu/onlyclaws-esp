package app.onlyclaws.android

import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined
import java.io.File

/**
 * A name points at one private file. Scripts read it back. The screen does not.
 *
 *   keys.get("deepseek")
 *   keys.set("deepseek", "…")
 *   keys.has("deepseek")
 */
class KeysPlugin(root: File) : JsPlugin {
    private val dir = File(root, "keys")

    override fun install(cx: JsContext, scope: Scriptable) {
        val api = Api()
        api.parentScope = scope
        ScriptableObject.putProperty(scope, "keys", api)
    }

    private fun file(name: String): File? {
        if (!name.matches(NAME)) return null
        return File(dir, name)
    }

    private fun read(name: String): String {
        val target = file(name) ?: return ""
        if (!target.isFile) return ""
        return runCatching { target.readText() }.getOrDefault("").trim()
    }

    private fun write(name: String, value: String): Boolean {
        val target = file(name) ?: return false
        val text = value.trim()
        if (text.isEmpty() || text.length > 400 || text.any { it == '\n' || it == '\r' }) return false
        dir.mkdirs()
        target.writeText(text)
        return true
    }

    private inner class Api : ScriptableObject() {
        override fun getClassName(): String = "keys"

        override fun get(name: String, start: Scriptable?): Any = when (name) {
            "get" -> textFn { read(text(it)) }
            "has" -> boolFn { read(text(it)).isNotEmpty() }
            "set" -> setFn
            else -> NOT_FOUND
        }

        private val setFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                val name = if (args.isNullOrEmpty()) "" else JsContext.toString(args[0])
                val value = if (args == null || args.size < 2) "" else JsContext.toString(args[1])
                return write(name, value)
            }
        }

        private fun textFn(body: (Array<out Any>?) -> String) = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                return body(args)
            }
        }

        private fun boolFn(body: (Array<out Any>?) -> Boolean) = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                return body(args)
            }
        }

        private fun text(args: Array<out Any>?): String =
            if (args.isNullOrEmpty()) "" else JsContext.toString(args[0])
    }

    companion object {
        private val NAME = Regex("[a-z0-9_-]{1,32}")
    }
}
