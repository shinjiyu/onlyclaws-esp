package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OverlayTouchTest {
    @Test
    fun fullScreenWashLetsTheLauncherSwipe() {
        val screenW = 360f
        val screenH = 780f
        val bands = (0 until 14).map { TouchBox(screenW, screenH / 14f + 1f) }
        val nebula = TouchBox(176f, 176f)
        val star = TouchBox(4f, 4f)
        val keep = chooseTouchBoxes(bands + nebula + star, screenW, screenH)
        assertEquals(bands.size + 2, keep.size)
        bands.indices.forEach { assertFalse(keep[it]) }
        assertFalse(keep[bands.size])
        assertTrue(keep.last())
    }

    @Test
    fun aShortBarStillReceivesTaps() {
        val bar = TouchBox(360f, 48f)
        val keep = chooseTouchBoxes(listOf(bar), 360f, 780f)
        assertTrue(keep[0])
    }
}