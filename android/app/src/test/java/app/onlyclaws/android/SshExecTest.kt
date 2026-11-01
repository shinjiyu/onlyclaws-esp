package app.onlyclaws.android

import org.apache.sshd.server.Environment
import org.apache.sshd.server.ExitCallback
import org.apache.sshd.server.SshServer
import org.apache.sshd.server.channel.ChannelSession
import org.apache.sshd.server.command.Command
import org.apache.sshd.server.keyprovider.SimpleGeneratorHostKeyProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.InputStream
import java.io.OutputStream
import java.nio.file.Files

class SshExecTest {
    @Test
    fun runsOneCommandAndRemembersTheHostKey() {
        val server = SshServer.setUpDefaultServer()
        val keyFile = Files.createTempFile("host", "key")
        server.port = 0
        server.keyPairProvider = SimpleGeneratorHostKeyProvider(keyFile)
        server.passwordAuthenticator = org.apache.sshd.server.auth.password.PasswordAuthenticator { user, password, _ ->
            user == "me" && password == "secret"
        }
        server.commandFactory = org.apache.sshd.server.command.CommandFactory { _, command ->
            Reply("out:$command", "err")
        }
        server.start()
        val known = Files.createTempFile("known", "txt").toFile()
        try {
            val ssh = SshExec(known)
            val port = server.port
            val ok = ssh.exec(SshExec.Spec(host = "127.0.0.1", port = port, user = "me", password = "secret", command = "uname"))
            assertEquals(ok.error, "", ok.error)
            assertEquals(0, ok.code)
            assertEquals("out:uname", ok.stdout)
            assertEquals("err", ok.stderr)
            assertTrue(ok.fingerprint.startsWith("SHA256:"))
            val again = ssh.exec(SshExec.Spec(host = "127.0.0.1", port = port, user = "me", password = "nope", command = "uname"))
            assertEquals("认证失败", again.error)
            known.writeText("127.0.0.1 $port SHA256:different\n")
            val changed = ssh.exec(SshExec.Spec(host = "127.0.0.1", port = port, user = "me", password = "secret", command = "uname"))
            assertEquals("主机指纹变了", changed.error)
            val pinned = ssh.exec(
                SshExec.Spec(
                    host = "127.0.0.1",
                    port = port,
                    user = "me",
                    password = "secret",
                    command = "id",
                    fingerprint = ok.fingerprint,
                ),
            )
            assertEquals(pinned.error, "", pinned.error)
            assertEquals("out:id", pinned.stdout)
        } finally {
            server.stop()
        }
    }

    private class Reply(private val stdout: String, private val stderr: String) : Command {
        private lateinit var out: OutputStream
        private lateinit var err: OutputStream
        private lateinit var exit: ExitCallback

        override fun setInputStream(input: InputStream) {}
        override fun setOutputStream(output: OutputStream) { out = output }
        override fun setErrorStream(error: OutputStream) { err = error }
        override fun setExitCallback(callback: ExitCallback) { exit = callback }
        override fun start(channel: ChannelSession, env: Environment) {
            out.write(stdout.toByteArray())
            out.flush()
            err.write(stderr.toByteArray())
            err.flush()
            exit.onExit(0)
        }
        override fun destroy(channel: ChannelSession) {}
    }
}
