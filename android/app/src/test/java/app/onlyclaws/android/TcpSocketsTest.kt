package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import java.util.Base64
import java.util.concurrent.atomic.AtomicInteger

class TcpSocketsTest {
    @Test
    fun echoesBytesAndCloses() {
        val port = AtomicInteger()
        val server = ServerSocket(0)
        port.set(server.localPort)
        val thread = Thread {
            server.accept().use { client ->
                val buf = ByteArray(16)
                val n = client.getInputStream().read(buf)
                client.getOutputStream().write(buf, 0, n)
                client.getOutputStream().write(byteArrayOf(0, 255.toByte(), 1))
                client.getOutputStream().flush()
            }
        }
        thread.start()
        try {
            val tcp = TcpSockets()
            val opened = tcp.open("127.0.0.1", port.get(), 5_000)
            assertEquals("", opened.error)
            assertEquals("", tcp.send(opened.id, "hi".toByteArray()))
            val raw = java.io.ByteArrayOutputStream()
            repeat(4) {
                if (raw.size() >= 5) return@repeat
                val got = tcp.recv(opened.id, 16, 5_000)
                assertEquals(got.error, "", got.error)
                if (got.n > 0) raw.write(Base64.getDecoder().decode(got.b64))
            }
            val bytes = raw.toByteArray()
            assertEquals(5, bytes.size)
            assertEquals("hi", String(bytes, 0, 2, Charsets.UTF_8))
            assertEquals(0, bytes[2].toInt())
            assertEquals(-1, bytes[3].toInt())
            tcp.close(opened.id)
            val gone = tcp.recv(opened.id, 8, 1_000)
            assertEquals("连接不在", gone.error)
        } finally {
            server.close()
            thread.join(2_000)
        }
    }

    @Test
    fun rejectsABadPort() {
        val opened = TcpSockets().open("127.0.0.1", 0, 1_000)
        assertEquals(0, opened.id)
        assertEquals("端口无效", opened.error)
    }
}

class HostKeysTest {
    @Test
    fun firstKeyIsSavedAndAChangeIsRefusedUnlessPinned() {
        assertEquals(HostKeys.Decision.SAVE, HostKeys.decide(null, "SHA256:a", ""))
        assertEquals(HostKeys.Decision.OK, HostKeys.decide("SHA256:a", "SHA256:a", ""))
        assertEquals(HostKeys.Decision.REJECT_CHANGED, HostKeys.decide("SHA256:a", "SHA256:b", ""))
        assertEquals(HostKeys.Decision.REJECT_PIN, HostKeys.decide("SHA256:a", "SHA256:b", "SHA256:a"))
        assertEquals(HostKeys.Decision.SAVE, HostKeys.decide("SHA256:a", "SHA256:b", "SHA256:b"))
    }

    @Test
    fun fileRoundTrip() {
        val file = kotlin.io.path.createTempFile("known").toFile()
        HostKeys.write(file, "h", 22, "SHA256:a")
        assertEquals("SHA256:a", HostKeys.read(file, "h", 22))
        HostKeys.write(file, "h", 22, "SHA256:b")
        assertEquals("SHA256:b", HostKeys.read(file, "h", 22))
        assertTrue(file.readText().lines().count { it.startsWith("h 22 ") } == 1)
    }
}
