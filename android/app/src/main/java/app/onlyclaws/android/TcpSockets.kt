package app.onlyclaws.android

import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/** Outbound TCP. A script connects; it cannot listen. */
class TcpSockets(
    private val maxOpen: Int = 4,
) {
    private val open = ConcurrentHashMap<Int, Socket>()
    private val nextId = AtomicInteger(1)

    fun open(host: String, port: Int, timeoutMs: Long): Opened {
        val target = host.trim()
        if (target.isEmpty() || target.length > 253 || target.any { it.isWhitespace() || it == '/' }) {
            return Opened(0, "地址无效")
        }
        if (port !in 1..65535) return Opened(0, "端口无效")
        if (open.size >= maxOpen) return Opened(0, "连接太多")
        val timeout = timeoutMs.coerceIn(MIN_TIMEOUT_MS, MAX_TIMEOUT_MS).toInt()
        val socket = Socket()
        try {
            socket.connect(InetSocketAddress(target, port), timeout)
            socket.soTimeout = timeout
            socket.tcpNoDelay = true
        } catch (t: Throwable) {
            socket.closeQuietly()
            return Opened(0, netError(t))
        }
        val id = nextId.getAndIncrement()
        open[id] = socket
        return Opened(id, "")
    }

    fun send(id: Int, bytes: ByteArray): String {
        if (bytes.size > MAX_BYTES) return "发送过大"
        val socket = open[id] ?: return "连接不在"
        return try {
            socket.getOutputStream().write(bytes)
            socket.getOutputStream().flush()
            ""
        } catch (t: Throwable) {
            netError(t)
        }
    }

    fun recv(id: Int, maxBytes: Int, timeoutMs: Long): Received {
        val socket = open[id] ?: return Received("", "", 0, eof = true, error = "连接不在")
        val cap = maxBytes.coerceIn(1, MAX_BYTES)
        val timeout = timeoutMs.coerceIn(MIN_TIMEOUT_MS, MAX_TIMEOUT_MS).toInt()
        return try {
            socket.soTimeout = timeout
            val input = socket.getInputStream()
            val buf = ByteArray(cap)
            val n = input.read(buf)
            if (n < 0) return Received("", "", 0, eof = true, error = "")
            var total = n
            while (total < cap && input.available() > 0) {
                val m = input.read(buf, total, cap - total)
                if (m <= 0) break
                total += m
            }
            val slice = buf.copyOf(total)
            Received(
                text = String(slice, Charsets.UTF_8),
                b64 = Base64.getEncoder().encodeToString(slice),
                n = total,
                eof = false,
                error = "",
            )
        } catch (_: SocketTimeoutException) {
            Received("", "", 0, eof = false, error = "超时")
        } catch (t: Throwable) {
            Received("", "", 0, eof = false, error = netError(t))
        }
    }

    fun close(id: Int) {
        open.remove(id)?.closeQuietly()
    }

    fun closeAll() {
        val ids = open.keys.toList()
        ids.forEach { close(it) }
    }

    data class Opened(val id: Int, val error: String)

    data class Received(val text: String, val b64: String, val n: Int, val eof: Boolean, val error: String)

    companion object {
        const val MAX_BYTES = 256 * 1024
        private const val MIN_TIMEOUT_MS = 1_000L
        private const val MAX_TIMEOUT_MS = 120_000L

        fun bytesOf(payload: String?): ByteArray? {
            if (payload == null) return null
            val json = runCatching { org.json.JSONObject(payload) }.getOrNull()
            if (json == null) return payload.toByteArray(Charsets.UTF_8)
            if (json.has("b64")) {
                return try {
                    Base64.getDecoder().decode(json.optString("b64"))
                } catch (_: IllegalArgumentException) {
                    null
                }
            }
            if (json.has("text")) return json.optString("text").toByteArray(Charsets.UTF_8)
            return null
        }
    }
}

private fun Socket.closeQuietly() {
    try {
        close()
    } catch (_: Throwable) {
    }
}

private fun netError(t: Throwable): String {
    val chain = generateSequence(t) { it.cause }.take(6).toList()
    if (chain.any { it is SocketTimeoutException }) return "超时"
    if (chain.any { it is java.net.UnknownHostException || it is java.net.ConnectException }) return "连接失败"
    return "连接失败"
}
