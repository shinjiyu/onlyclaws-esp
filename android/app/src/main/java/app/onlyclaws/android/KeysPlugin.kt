package app.onlyclaws.android

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

    override fun install(scope: JsScope) = scope.define("keys") {
        fn("get") { read(it.string(0)) }
        fn("has") { read(it.string(0)).isNotEmpty() }
        fn("set") { write(it.string(0), it.string(1)) }
    }

    private fun file(name: String): File? {
        if (!name.matches(NAME)) return null
        return File(dir, name)
    }

    internal fun read(name: String): String {
        val target = file(name) ?: return ""
        if (!target.isFile) return ""
        return runCatching { target.readText() }.getOrDefault("").trim()
    }

    internal fun write(name: String, value: String): Boolean {
        val target = file(name) ?: return false
        val text = value.trim()
        if (text.isEmpty() || text.length > 400 || text.any { it == '\n' || it == '\r' }) return false
        dir.mkdirs()
        target.writeText(text)
        return true
    }

    companion object {
        private val NAME = Regex("[a-z0-9_-]{1,32}")
    }
}
