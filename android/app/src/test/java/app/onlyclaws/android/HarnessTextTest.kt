package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HarnessTextTest {
    private val todo = """
        // 标题：待办
        var items = [];
        function onStart() { oca.log("ok"); }
    """.trimIndent()

    @Test
    fun takesTheFirstFencedBlock() {
        val reply = "好的。\n```js\n$todo\n```\n另外一段：\n```js\nfunction onStart() {}\n```"
        assertEquals(todo, HarnessText.extractScript(reply))
    }

    @Test
    fun acceptsAnUntaggedFenceAndABareScript() {
        assertEquals(todo, HarnessText.extractScript("```\n$todo\n```"))
        assertEquals(todo, HarnessText.extractScript(todo))
        assertNull(HarnessText.extractScript("我做不到这个。"))
    }

    @Test
    fun checkPassesEs5WithOnStart() {
        assertNull(HarnessText.check(todo))
    }

    @Test
    fun checkReportsSyntaxErrorWithLine() {
        val problem = HarnessText.check("function onStart() {\n  var a = ;\n}")
        assertNotNull(problem)
        assertTrue(problem!!, problem.startsWith("第 2 行"))
    }

    @Test
    fun checkRejectsWhatTheContainerCannotParse() {
        assertNotNull(HarnessText.check("let x = 1;\nfunction onStart() {}"))
        assertNotNull(HarnessText.check("class A {}\nfunction onStart() {}"))
        assertNotNull(HarnessText.check("for (var v of [1]) {}\nfunction onStart() {}"))
    }

    @Test
    fun checkWantsOnStart() {
        assertEquals("没有 onStart", HarnessText.check("var a = 1;"))
    }

    @Test
    fun titleComesFromTheFirstLine() {
        assertEquals("待办", HarnessText.title(todo))
        assertEquals("新界面", HarnessText.title("function onStart() {}"))
    }

    @Test
    fun keyLooksLikeAnApiKeyOnly() {
        assertTrue(HarnessText.looksLikeKey("  sk-0123456789abcdef0123  "))
        assertFalse(HarnessText.looksLikeKey("sk-short"))
        assertFalse(HarnessText.looksLikeKey("帮我做个计时器 sk-0123456789abcdef0123"))
    }

    @Test
    fun promptCarriesCurrentScriptWithoutMarkAndRecentAsks() {
        val current = HarnessText.MARK + "\n" + todo
        val prompt = HarnessText.userPrompt("加一个清空按钮", current, listOf("做个待办"), "item is undefined")
        assertTrue(prompt.contains("1. 做个待办"))
        assertTrue(prompt.contains("现在要的：加一个清空按钮"))
        assertTrue(prompt.contains(todo))
        assertFalse(prompt.contains(HarnessText.MARK))
        assertTrue(prompt.contains("item is undefined"))
    }

    @Test
    fun freshPromptHasNoScript() {
        val prompt = HarnessText.userPrompt("做个计时器", null, emptyList(), "")
        assertEquals("现在要的：做个计时器\n", prompt)
    }

    @Test
    fun theSystemExampleItselfPasses() {
        val example = HarnessText.extractScript(HarnessText.SYSTEM.substringAfter("例子："))
        assertNotNull(example)
        assertNull(HarnessText.check(example!!))
    }
}
