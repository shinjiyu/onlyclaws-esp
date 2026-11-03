package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PresetCatalogTest {
    @Test
    fun parseList_keepsOcaRowsAndZhTitles() {
        val body = """
            {
              "success": true,
              "kind": "oca",
              "presets": [
                {
                  "id": "bilibili-play",
                  "kind": "oca",
                  "filename": "bilibili-play.js",
                  "bytes": 12,
                  "title": {"zh": "B 站陪看", "en": "Bilibili play"},
                  "summary": {"zh": "摘要", "en": "summary"}
                },
                {
                  "id": "snake-lan",
                  "kind": "esp32",
                  "filename": "snake-lan.lua",
                  "bytes": 3,
                  "title": {"zh": "蛇", "en": "Snake"},
                  "summary": {"zh": "x", "en": "x"}
                },
                {
                  "id": "oca-empty",
                  "kind": "oca",
                  "filename": "empty.js",
                  "bytes": 4,
                  "title": "Empty",
                  "summary": "stop"
                }
              ]
            }
        """.trimIndent()
        val items = PresetCatalog.parseList(body)
        assertEquals(listOf("bilibili-play", "oca-empty"), items.map { it.id })
        assertEquals("B 站陪看", items[0].title)
        assertEquals("摘要", items[0].summary)
        assertEquals("Empty", items[1].title)
        assertEquals(12, items[0].bytes)
    }

    @Test
    fun localized_fallsBackToEn() {
        assertEquals("Hi", PresetCatalog.localized(org.json.JSONObject("""{"en":"Hi"}""")))
        assertEquals("", PresetCatalog.localized(null))
        assertTrue(OcCloud.presetsListUrl("oca").startsWith("https://"))
        assertTrue(OcCloud.presetSourceUrl("bilibili-play").contains("inline=1"))
    }
}
