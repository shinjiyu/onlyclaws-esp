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
    fun parseAttachesAUserImage() {
        val messages = LlmChat.parse(
            """{"messages":[{"role":"user","content":"看","image":"abcd"}]}""",
        )!!
        val content = messages.getJSONObject(0).getJSONArray("content")
        assertEquals("text", content.getJSONObject(0).getString("type"))
        assertEquals("看", content.getJSONObject(0).getString("text"))
        assertEquals(
            "data:image/jpeg;base64,abcd",
            content.getJSONObject(1).getJSONObject("image_url").getString("url"),
        )
    }

    @Test
    fun parseKeepsADataUrlAndRejectsJunk() {
        val messages = LlmChat.parse(
            """{"messages":[{"role":"user","image":"data:image/png;base64,aaaa"}]}""",
        )!!
        val content = messages.getJSONObject(0).getJSONArray("content")
        assertEquals("看这张图", content.getJSONObject(0).getString("text"))
        assertEquals(
            "data:image/png;base64,aaaa",
            content.getJSONObject(1).getJSONObject("image_url").getString("url"),
        )
        assertNull(LlmChat.parse("""{"messages":[{"role":"user","content":"看","image":"not an image"}]}"""))
        assertEquals("图片太大或不是 base64", LlmChat.explain("""{"messages":[{"role":"user","content":"看","image":"***"}]}"""))
    }

    @Test
    fun readOpenAiMessage() {
        val body = """{"choices":[{"message":{"role":"assistant","content":"  汪  "}}]}"""
        assertEquals("汪", LlmChat.readText(body))
        assertNull(LlmChat.readText("{}"))
        val parts = """{"choices":[{"message":{"content":[{"type":"text","text":"好"},{"type":"text","text":"的"}]}}]}"""
        assertEquals("好的", LlmChat.readText(parts))
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
