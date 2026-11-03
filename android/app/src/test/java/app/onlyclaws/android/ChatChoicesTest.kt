package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatChoicesTest {
    @Test
    fun parsesChoiceBlock() {
        val raw = """
            要换哪种壁纸？
            <<<choices
            黑客帝国代码雨
            下雪
            保持现在这样
            >>>
        """.trimIndent()
        val parsed = ChatChoices.parse(raw)
        assertEquals("要换哪种壁纸？", parsed.text)
        assertEquals(
            listOf("黑客帝国代码雨", "下雪", "保持现在这样"),
            parsed.choices,
        )
    }

    @Test
    fun acceptsChineseFenceName() {
        val parsed = ChatChoices.parse("选一个\n<<<选项\n确认\n取消\n>>>")
        assertEquals(listOf("确认", "取消"), parsed.choices)
        assertEquals("选一个", parsed.text)
    }

    @Test
    fun hidesPartialFenceWhileStreaming() {
        val shown = ChatChoices.displayWhileStreaming("先说一句\n<<<choices\n还没写完")
        assertEquals("先说一句", shown)
        assertTrue(ChatChoices.parse("先说一句\n<<<choices\n还没写完").choices.isEmpty())
    }
}
