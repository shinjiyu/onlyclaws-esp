package app.onlyclaws.android

import net.schmizz.sshj.SSHClient
import net.schmizz.sshj.common.Buffer
import net.schmizz.sshj.transport.verification.HostKeyVerifier
import net.schmizz.sshj.userauth.password.PasswordFinder
import net.schmizz.sshj.userauth.password.Resource
import org.json.JSONObject
import java.io.File
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.MessageDigest
import java.security.PublicKey
import java.util.Base64
import java.util.concurrent.TimeUnit

/** One command over SSH. The first host key is kept; a later change is refused. */
class SshExec(private val known: File) {
    fun exec(spec: Spec): Result {
        if (spec.host.isEmpty() || spec.host.length > 253 || spec.host.any { it.isWhitespace() }) {
            return fail("地址无效")
        }
        if (spec.port !in 1..65535) return fail("端口无效")
        if (spec.user.isEmpty() || spec.user.length > 64) return fail("缺少 user")
        if (spec.command.isEmpty()) return fail("缺少 command")
        if (spec.command.length > 8_000) return fail("命令过长")
        if (spec.password.isNullOrEmpty() && spec.privateKey.isNullOrBlank()) {
            return fail("需要 password 或 privateKey")
        }
        val pinned = spec.fingerprint.trim()
        val stored = HostKeys.read(known, spec.host, spec.port)
        var actual = ""
        var decision = HostKeys.Decision.OK
        val client = SSHClient()
        try {
            client.connectTimeout = spec.timeoutMs.coerceIn(1_000, 120_000).toInt()
            client.timeout = client.connectTimeout
            client.addHostKeyVerifier(object : HostKeyVerifier {
                override fun verify(hostname: String, port: Int, key: PublicKey): Boolean {
                    actual = fingerprint(key)
                    decision = HostKeys.decide(stored, actual, pinned)
                    return decision == HostKeys.Decision.OK || decision == HostKeys.Decision.SAVE
                }

                override fun findExistingAlgorithms(hostname: String, port: Int): List<String> = emptyList()
            })
            client.connect(spec.host, spec.port)
            if (decision == HostKeys.Decision.SAVE) HostKeys.write(known, spec.host, spec.port, actual)
            if (!spec.privateKey.isNullOrBlank()) {
                val finder = object : PasswordFinder {
                    override fun reqPassword(resource: Resource<*>?): CharArray = spec.passphrase.orEmpty().toCharArray()
                    override fun shouldRetry(resource: Resource<*>?) = false
                }
                val keys = client.loadKeys(spec.privateKey, null, finder)
                client.authPublickey(spec.user, keys)
            } else {
                client.authPassword(spec.user, spec.password)
            }
            client.startSession().use { session ->
                session.exec(spec.command).use { cmd ->
                    val out = java.io.ByteArrayOutputStream()
                    val err = java.io.ByteArrayOutputStream()
                    val readers = listOf(
                        Thread { copy(cmd.inputStream, out) },
                        Thread { copy(cmd.errorStream, err) },
                    )
                    readers.forEach { it.isDaemon = true; it.start() }
                    cmd.join(spec.timeoutMs.coerceIn(1_000, 120_000).toLong(), TimeUnit.MILLISECONDS)
                    val code = cmd.exitStatus
                    client.disconnect()
                    readers.forEach { it.join(1_000) }
                    if (code == null) {
                        return Result(-1, text(out), text(err), "超时", actual)
                    }
                    return Result(code, text(out), text(err), "", actual)
                }
            }
        } catch (t: Throwable) {
            return fail(sshError(t, decision, actual), actual)
        } finally {
            try {
                client.disconnect()
            } catch (_: Throwable) {
            }
        }
    }

    data class Spec(
        val host: String,
        val port: Int = 22,
        val user: String,
        val password: String? = null,
        val privateKey: String? = null,
        val passphrase: String? = null,
        val command: String,
        val timeoutMs: Long = 20_000,
        val fingerprint: String = "",
    )

    data class Result(
        val code: Int,
        val stdout: String,
        val stderr: String,
        val error: String,
        val fingerprint: String,
    )

    companion object {
        const val MAX_OUT = 256 * 1024

        fun parse(json: String?): Spec? {
            val obj = json?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return null
            return Spec(
                host = obj.optString("host").trim(),
                port = if (obj.has("port")) obj.optInt("port", 22) else 22,
                user = obj.optString("user").trim(),
                password = obj.optString("password").ifBlank { null },
                privateKey = obj.optString("privateKey").ifBlank { null },
                passphrase = obj.optString("passphrase").ifBlank { null },
                command = obj.optString("command"),
                timeoutMs = if (obj.has("timeoutMs")) obj.optLong("timeoutMs", 20_000) else 20_000,
                fingerprint = obj.optString("fingerprint").trim(),
            )
        }

        fun fingerprint(key: PublicKey): String {
            val blob = Buffer.PlainBuffer().putPublicKey(key).compactData
            val digest = MessageDigest.getInstance("SHA-256").digest(blob)
            return "SHA256:" + Base64.getEncoder().withoutPadding().encodeToString(digest)
        }

        private fun copy(input: java.io.InputStream, out: java.io.ByteArrayOutputStream) {
            try {
                val buf = ByteArray(8192)
                while (out.size() < MAX_OUT) {
                    val n = input.read(buf)
                    if (n < 0) break
                    val room = MAX_OUT - out.size()
                    out.write(buf, 0, minOf(n, room))
                }
            } catch (_: Throwable) {
            }
        }

        private fun text(out: java.io.ByteArrayOutputStream) = out.toByteArray().toString(Charsets.UTF_8)

        private fun fail(error: String, fingerprint: String = "") = Result(-1, "", "", error, fingerprint)

        private fun sshError(t: Throwable, decision: HostKeys.Decision, actual: String): String {
            if (decision == HostKeys.Decision.REJECT_PIN) return "指纹不符"
            if (decision == HostKeys.Decision.REJECT_CHANGED) return "主机指纹变了"
            val chain = generateSequence(t) { it.cause }.take(8).toList()
            if (chain.any { it is SocketTimeoutException }) return "超时"
            if (chain.any { it is UnknownHostException || it is ConnectException }) return "连接失败"
            val message = t.message.orEmpty()
            if (message.contains("PRIVATE") || message.contains("password", ignoreCase = true)) return "认证失败"
            if (message.contains("auth", ignoreCase = true) || message.contains("Auth")) return "认证失败"
            if (actual.isNotEmpty() && message.contains("reject", ignoreCase = true)) return "主机指纹变了"
            return "连接失败"
        }
    }
}

/** Remembered SSH host keys: one `host port fingerprint` line. */
object HostKeys {
    enum class Decision { OK, SAVE, REJECT_PIN, REJECT_CHANGED }

    fun decide(stored: String?, actual: String, pinned: String): Decision {
        if (pinned.isNotEmpty() && pinned != actual) return Decision.REJECT_PIN
        if (stored.isNullOrEmpty()) return Decision.SAVE
        if (stored == actual) return Decision.OK
        if (pinned.isNotEmpty() && pinned == actual) return Decision.SAVE
        return Decision.REJECT_CHANGED
    }

    fun read(file: File, host: String, port: Int): String? {
        if (!file.isFile) return null
        val prefix = "$host $port "
        return file.readLines().firstOrNull { it.startsWith(prefix) }?.removePrefix(prefix)?.trim()?.ifBlank { null }
    }

    fun write(file: File, host: String, port: Int, fingerprint: String) {
        val prefix = "$host $port "
        val lines = if (file.isFile) file.readLines().filterNot { it.startsWith(prefix) } else emptyList()
        file.parentFile?.mkdirs()
        file.writeText((lines + "$prefix$fingerprint").joinToString("\n") + "\n")
    }
}
