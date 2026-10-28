package app.onlyclaws.android

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.io.ByteArrayOutputStream
import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.UnknownHostException
import java.util.Locale
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException

/**
 * One HTTPS call. The script decides whether to retry.
 * Connect budget is 20s on [client]. [HttpSpec.timeoutMs] is the whole call.
 */
class HttpCall(
    private val client: OkHttpClient,
    private val maxBytes: Int = MAX_BYTES,
) {
    fun perform(spec: HttpSpec): HttpOutcome {
        val url = spec.url.trim()
        if (url.isEmpty()) return fail("缺少 url")
        val httpUrl = try {
            url.toHttpUrl()
        } catch (_: IllegalArgumentException) {
            return fail("地址无效")
        }
        if (httpUrl.scheme != "https") return fail("只接受 https")

        val method = spec.method.trim().uppercase(Locale.US)
        if (method !in METHODS) return fail("方法无效")
        if (method !in WITH_BODY && !spec.body.isNullOrEmpty()) return fail("这个方法不能带 body")

        val body = spec.body
        if (body != null && body.toByteArray(Charsets.UTF_8).size > maxBytes) return fail("请求过大")

        val contentType = spec.headers.entries.firstOrNull { it.key.equals("Content-Type", ignoreCase = true) }?.value
        val media = if (contentType == null) {
            JSON_MEDIA
        } else {
            contentType.toMediaTypeOrNull() ?: return fail("Content-Type 无效")
        }

        val request = try {
            val builder = Request.Builder().url(httpUrl)
            for ((name, value) in spec.headers) {
                if (name.equals("Content-Type", ignoreCase = true)) continue
                if (name.lowercase(Locale.US) in HOP) continue
                builder.header(name, value)
            }
            if (method in WITH_BODY) {
                builder.method(method, (body ?: "").toRequestBody(media))
            } else {
                builder.method(method, null)
            }
            builder.build()
        } catch (_: IllegalArgumentException) {
            return fail("请求无效")
        }

        val timeoutMs = spec.timeoutMs.coerceIn(MIN_TIMEOUT_MS, MAX_TIMEOUT_MS)
        return try {
            val call = client.newCall(request)
            call.timeout().timeout(timeoutMs, TimeUnit.MILLISECONDS)
            call.execute().use { read(it) }
        } catch (t: Throwable) {
            fail(netError(t))
        }
    }

    private fun read(response: Response): HttpOutcome {
        if (response.request.url.scheme != "https") return fail("只接受 https")
        val headers = LinkedHashMap<String, String>()
        for (name in response.headers.names()) {
            headers[name.lowercase(Locale.US)] = response.headers.values(name).joinToString(", ")
        }
        val payload = response.body
        val charset = payload?.contentType()?.charset(Charsets.UTF_8) ?: Charsets.UTF_8
        val stream = payload?.byteStream()
        val (bytes, tooLong) = if (stream == null) {
            ByteArray(0) to false
        } else {
            stream.use { readCapped(it, maxBytes) }
        }
        return HttpOutcome(
            status = response.code,
            body = String(bytes, charset),
            error = if (tooLong) "响应过长" else "",
            headers = headers,
        )
    }

    companion object {
        const val MAX_BYTES = 2 * 1024 * 1024
        private const val MIN_TIMEOUT_MS = 1_000L
        private const val MAX_TIMEOUT_MS = 120_000L
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
        private val METHODS = setOf("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
        private val WITH_BODY = setOf("POST", "PUT", "PATCH", "DELETE")
        private val HOP = setOf(
            "host",
            "content-length",
            "connection",
            "transfer-encoding",
            "keep-alive",
            "upgrade",
            "proxy-authorization",
            "te",
            "trailer",
        )

        fun client(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .onlyHttps()
            .build()
    }
}

fun OkHttpClient.Builder.onlyHttps(): OkHttpClient.Builder = addNetworkInterceptor { chain ->
    if (chain.request().url.scheme != "https") throw HttpsOnlyException()
    chain.proceed(chain.request())
}

class HttpsOnlyException : java.io.IOException("https")

data class HttpSpec(
    val url: String,
    val method: String = "GET",
    val headers: Map<String, String> = emptyMap(),
    val body: String? = null,
    val timeoutMs: Long = 60_000,
)

data class HttpOutcome(
    val status: Int,
    val body: String,
    val error: String,
    val headers: Map<String, String>,
)

private fun fail(error: String) = HttpOutcome(0, "", error, emptyMap())

private fun readCapped(stream: java.io.InputStream, maxBytes: Int): Pair<ByteArray, Boolean> {
    val out = ByteArrayOutputStream()
    val buf = ByteArray(8192)
    var total = 0
    while (true) {
        val n = stream.read(buf)
        if (n < 0) return out.toByteArray() to false
        val room = maxBytes - total
        if (n > room) {
            if (room > 0) out.write(buf, 0, room)
            return out.toByteArray() to true
        }
        out.write(buf, 0, n)
        total += n
    }
}

private fun netError(t: Throwable): String {
    val chain = generateSequence(t) { it.cause }.take(8).toList()
    if (chain.any { it is HttpsOnlyException }) return "只接受 https"
    if (chain.any { it is InterruptedIOException }) return "超时"
    if (chain.any { it is UnknownHostException || it is ConnectException }) return "连接失败"
    if (chain.any { it is SSLException }) return "证书失败"
    return "请求失败"
}
