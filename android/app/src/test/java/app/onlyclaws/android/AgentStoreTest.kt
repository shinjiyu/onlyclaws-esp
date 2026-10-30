package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class AgentStoreTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun writesPiAuthJsonAndMigratesTheOldDeepseekKey() {
        val root = tmp.newFolder()
        val old = java.io.File(java.io.File(root, "keys").apply { mkdirs() }, "deepseek")
        old.writeText("sk-0123456789abcdef0123")
        val store = AgentStore(root)
        assertEquals("sk-0123456789abcdef0123", store.key("deepseek"))
        store.writeKey("openai", "sk-openai-key-12345678")
        store.writeSettings(AgentStore.Settings(provider = "openai", model = "gpt-4o-mini"))
        val again = AgentStore(root)
        assertEquals("sk-openai-key-12345678", again.key("openai"))
        assertEquals("openai", again.settings().provider)
        assertTrue(java.io.File(root, "agent/auth.json").readText().contains("\"type\":\"api_key\""))
    }
}
