package app.onlyclaws.android

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenDocTest {
    @Test
    fun fragmentGetsADocumentAndTheClickBridge() {
        val html = ScreenDoc.document("""<button data-action="add">添加</button>""")
        assertTrue(html.contains("<!DOCTYPE html>"))
        assertTrue(html.contains("data-action"))
        assertTrue(html.contains("OcaScreen.action"))
    }

    @Test
    fun fullDocumentKeepsTheAuthorsMarkup() {
        val html = ScreenDoc.document("<html><body><svg data-action=\"go\"></svg></body></html>")
        assertTrue(html.startsWith("<html>"))
        assertTrue(html.trimEnd().endsWith("</script>"))
        assertTrue(html.contains("<svg data-action=\"go\"></svg>"))
    }

    @Test
    fun clickBecomesAnActionEvent() {
        val text = ScreenDoc.event("add", """{"draft":"星空","n":2,"on":true}""")
        val json = JSONObject(text!!)
        assertEquals("add", json.getString("action"))
        val context = json.getJSONObject("context")
        assertEquals("星空", context.getString("draft"))
        assertEquals(2, context.getInt("n"))
        assertEquals(true, context.getBoolean("on"))
    }

    @Test
    fun aBadActionIsDropped() {
        assertNull(ScreenDoc.event("go there", "{}"))
        assertNull(ScreenDoc.event("", "{}"))
    }
}
