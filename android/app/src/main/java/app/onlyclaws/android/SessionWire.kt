package app.onlyclaws.android

import android.content.Context
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Device session. Identity is files/session.json, not inside the apk.
 * One message at a time. A `js` tool replaces the script in the container.
 */
class SessionWire(
    context: Context,
    private val onScript: (source: String, reply: (Boolean) -> Unit) -> Unit,
    private val onState: (String) -> Unit,
) {
    private val dir = context.filesDir
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val io = Executors.newSingleThreadScheduledExecutor()
    private val connecting = AtomicBoolean(false)
    private var socket: WebSocket? = null
    private var opened = false
    private var stopped = false
    private var lastId = ""
    private var lastStatusAt = 0L

    fun start() {
        if (credentials() == null) {
            onState("未配置 session.json")
            return
        }
        onState("正在连接")
        io.scheduleWithFixedDelay({ tick() }, 0, 3, TimeUnit.SECONDS)
    }

    fun stop() {
        stopped = true
        opened = false
        socket?.close(1000, null)
        socket = null
        io.shutdownNow()
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }

    private fun tick() {
        if (stopped) return
        if (!opened) {
            connect()
            return
        }
        val now = System.currentTimeMillis()
        if (now - lastStatusAt >= 25_000) sendStatus()
    }

    private fun connect() {
        if (!connecting.compareAndSet(false, true)) return
        val creds = credentials() ?: run {
            connecting.set(false)
            return
        }
        val url = "wss://onlyclaws.world/epaper/api/v1/device/${creds.id}/session"
        val request = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer ${creds.token}")
            .build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                opened = true
                connecting.set(false)
                onState("已连接 ${creds.id}")
                webSocket.send(hello(creds.token))
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                onFrame(webSocket, text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                opened = false
                webSocket.close(code, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                opened = false
                connecting.set(false)
                onState("连接已断开")
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                opened = false
                connecting.set(false)
                onState("连接失败")
                Log.w(TAG, "session down: ${t.message}")
            }
        })
    }

    private fun onFrame(webSocket: WebSocket, text: String) {
        val frame = try {
            JSONObject(text)
        } catch (_: Exception) {
            return
        }
        when (frame.optString("type")) {
            "welcome" -> sendStatus()
            "message" -> onMessage(webSocket, frame.optJSONObject("message") ?: return)
        }
    }

    private fun onMessage(webSocket: WebSocket, message: JSONObject) {
        val id = message.optString("id")
        if (id.isEmpty()) return
        if (id == lastId) {
            ack(webSocket, id, true, 0)
            return
        }
        val source = if (message.optString("type") == "invoke") jsSource(message.optString("body")) else null
        if (source == null) {
            ack(webSocket, id, false, 0)
            return
        }
        val started = System.currentTimeMillis()
        onScript(source) { ok ->
            if (ok) lastId = id
            ack(webSocket, id, ok, System.currentTimeMillis() - started)
        }
    }

    private fun sendStatus() {
        lastStatusAt = System.currentTimeMillis()
        val meta = JSONObject().put("capabilities", org.json.JSONArray(listOf("container")))
        socket?.send(
            JSONObject()
                .put("type", "status")
                .put("fw", FW)
                .put("meta", meta)
                .toString(),
        )
    }

    private fun hello(token: String): String {
        val meta = JSONObject().put("capabilities", org.json.JSONArray(listOf("container")))
        return JSONObject()
            .put("type", "hello")
            .put("token", token)
            .put("fw", FW)
            .put("meta", meta)
            .toString()
    }

    private fun ack(webSocket: WebSocket, id: String, ok: Boolean, ms: Long) {
        webSocket.send(
            JSONObject()
                .put("type", "ack")
                .put("message_id", id)
                .put("ok", ok)
                .put("ms", ms)
                .toString(),
        )
    }

    private fun credentials(): Creds? {
        val file = File(dir, "session.json")
        if (!file.exists()) return null
        return try {
            val json = JSONObject(file.readText())
            val id = json.optString("device_id").trim().lowercase()
            val token = json.optString("token").trim()
            if (id.length < 4 || token.isEmpty()) null else Creds(id, token)
        } catch (_: Exception) {
            null
        }
    }

    private data class Creds(val id: String, val token: String)

    companion object {
        private const val TAG = "OcaSession"
        const val FW = "oca-0.7.0"

        fun jsSource(body: String): String? {
            val tools = try {
                JSONObject(body).optJSONArray("tools")
            } catch (_: Exception) {
                null
            } ?: return null
            for (i in 0 until tools.length()) {
                val step = tools.optJSONObject(i) ?: continue
                if (step.optString("tool") != "js") continue
                val direct = step.optString("source")
                if (direct.isNotEmpty()) return direct
                val fromArgs = step.optJSONObject("args")?.optString("source").orEmpty()
                if (fromArgs.isNotEmpty()) return fromArgs
            }
            return null
        }
    }
}
