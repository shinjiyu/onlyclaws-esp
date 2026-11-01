package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LlmChatTest {
    @Test
    fun parseWantsMessages() {
        assertNull(LlmChat.parse(null))
        assertNull(LlmChat.parse("{}"))
        assertNull(LlmChat.parse("""{"messages":[]}"""))
        assertNull(LlmChat.parse("""{"messages":[{"role":"user","content":""}]}"""))
        assertNull(LlmChat.parse("""{"messages":[{"role":"tool","content":"x"}]}"""))
    }

    @Test
    fun parseKeepsRolesAndOptionalSystem() {
        val messages = LlmChat.parse(
            """{"system":"你是桌宠","messages":[{"role":"user","content":"你好"},{"role":"assistant","content":"嗯"}]}""",
        )!!
        assertEquals(3, messages.length())
        assertEquals("system", messages.getJSONObject(0).getString("role"))
        assertEquals("你是桌宠", messages.getJSONObject(0).getString("content"))
        assertEquals("user", messages.getJSONObject(1).getString("role"))
    }

    @Test
    fun readOpenAiMessage() {
        val body = """{"choices":[{"message":{"role":"assistant","content":"  汪  "}}]}"""
        assertEquals("汪", LlmChat.readText(body))
        assertNull(LlmChat.readText("{}"))
    }

    @Test
    fun endpointsFollowTheSelectedProvider() {
        val deepseek = AgentStore.Settings(provider = "deepseek", model = "deepseek-flash")
        assertEquals("https://api.deepseek.com/v1/chat/completions", LlmEndpoints.chatUrl(deepseek))
        assertFalse(LlmEndpoints.usingCustom(deepseek))

        val custom = AgentStore.Settings(
            provider = "custom",
            model = "ignored",
            custom = AgentStore.Custom(id = "custom", baseUrl = "https://example.com/v1", model = "pet"),
        )
        assertTrue(LlmEndpoints.usingCustom(custom))
        assertEquals("https://example.com/v1/chat/completions", LlmEndpoints.chatUrl(custom))
        assertEquals("https://api.x.com/v1/chat/completions", LlmEndpoints.join("https://api.x.com/v1/chat/completions"))
    }

    @Test
    fun anthropicHasNoScriptEndpoint() {
        assertEquals("", LlmEndpoints.chatUrl(AgentStore.Settings(provider = "anthropic", model = "claude")))
    }
}
