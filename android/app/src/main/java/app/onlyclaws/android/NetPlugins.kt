package app.onlyclaws.android

import org.json.JSONObject
import java.io.File

/**
 * Outbound TCP.
 *
 *   socket.open({ host, port, timeoutMs }) → { id, error }
 *   socket.send(id, { text } | { b64 } | "text")
 *   socket.recv(id, { maxBytes, timeoutMs }) → { text, b64, n, eof, error }
 *   socket.close(id)
 */
class SocketPlugin : JsPlugin {
    private val tcp = TcpSockets()

    override fun install(scope: JsScope) = scope.define("socket") {
        fn("open") { open(it.json(0)) }
        fn("send") { send(it.number(0).toInt(), it.json(1)) }
        fn("recv") { recv(it.number(0).toInt(), it.json(1)) }
        fn("close") { tcp.close(it.number(0).toInt()) }
    }

    override fun beforeSwap() {
        tcp.closeAll()
    }

    private fun open(arg: String?): Map<String, Any> {
        val json = arg?.let { runCatching { JSONObject(it) }.getOrNull() }
            ?: return mapOf("id" to 0, "error" to "缺少 host")
        val opened = tcp.open(
            host = json.optString("host"),
            port = json.optInt("port", 0),
            timeoutMs = if (json.has("timeoutMs")) json.optLong("timeoutMs", 10_000) else 10_000,
        )
        return mapOf("id" to opened.id, "error" to opened.error)
    }

    private fun send(id: Int, payload: String?): String {
        val bytes = TcpSockets.bytesOf(payload) ?: return "缺少 text 或 b64"
        return tcp.send(id, bytes)
    }

    private fun recv(id: Int, arg: String?): Map<String, Any> {
        val json = arg?.let { runCatching { JSONObject(it) }.getOrNull() }
        val got = tcp.recv(
            id = id,
            maxBytes = json?.optInt("maxBytes", 65_536) ?: 65_536,
            timeoutMs = json?.optLong("timeoutMs", 10_000) ?: 10_000,
        )
        return mapOf(
            "text" to got.text,
            "b64" to got.b64,
            "n" to got.n,
            "eof" to got.eof,
            "error" to got.error,
        )
    }
}

/**
 * One SSH command, then the connection closes.
 *
 *   ssh.exec({ host, port, user, password | privateKey, passphrase, command, timeoutMs, fingerprint })
 *     → { code, stdout, stderr, error, fingerprint }
 */
class SshPlugin(known: File) : JsPlugin {
    private val ssh = SshExec(known)

    override fun install(scope: JsScope) = scope.define("ssh") {
        fn("exec") { exec(it.json(0)) }
    }

    private fun exec(arg: String?): Map<String, Any> {
        val spec = SshExec.parse(arg) ?: return result(SshExec.Result(-1, "", "", "缺少 host", ""))
        return result(ssh.exec(spec))
    }

    private fun result(r: SshExec.Result) = mapOf(
        "code" to r.code,
        "stdout" to r.stdout,
        "stderr" to r.stderr,
        "error" to r.error,
        "fingerprint" to r.fingerprint,
    )
}
