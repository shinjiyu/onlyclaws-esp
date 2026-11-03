package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AsrTextTest {
    @Test
    fun stripsSenseVoiceTags() {
        assertEquals("你好", AsrText.clean("<|zh|><|NEUTRAL|><|Speech|>你好"))
        assertEquals("我在", AsrText.clean("  <|zh|>我在  "))
    }

    @Test
    fun fillerIgnoresPunctuationAndHum() {
        assertTrue(AsrText.filler(""))
        assertTrue(AsrText.filler("。"))
        assertTrue(AsrText.filler("嗯"))
        assertFalse(AsrText.filler("我。"))
        assertFalse(AsrText.filler("你好"))
    }
}
