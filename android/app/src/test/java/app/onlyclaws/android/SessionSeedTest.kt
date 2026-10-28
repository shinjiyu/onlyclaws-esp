package app.onlyclaws.android

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class SessionSeedTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val first = """{"device_id":"oca000000001","token":"a"}""".toByteArray()
    private val second = """{"device_id":"oca000000001","token":"b"}""".toByteArray()

    @Test
    fun noPackagedSessionLeavesFilesAlone() {
        val dir = tmp.newFolder()
        File(dir, "session.json").writeText("hand")
        assertFalse(SessionSeed.apply(null, dir))
        assertFalse(SessionSeed.apply(ByteArray(0), dir))
        assertEquals("hand", File(dir, "session.json").readText())
    }

    @Test
    fun firstInstallWritesSession() {
        val dir = tmp.newFolder()
        assertTrue(SessionSeed.apply(first, dir))
        assertArrayEquals(first, File(dir, "session.json").readBytes())
        assertFalse(File(dir, "session.json.tmp").exists())
    }

    @Test
    fun samePackageKeepsHandEditedSession() {
        val dir = tmp.newFolder()
        SessionSeed.apply(first, dir)
        File(dir, "session.json").writeText("hand")
        assertFalse(SessionSeed.apply(first, dir))
        assertEquals("hand", File(dir, "session.json").readText())
    }

    @Test
    fun newPackageReplacesSession() {
        val dir = tmp.newFolder()
        SessionSeed.apply(first, dir)
        File(dir, "session.json").writeText("hand")
        assertTrue(SessionSeed.apply(second, dir))
        assertArrayEquals(second, File(dir, "session.json").readBytes())
    }
}
