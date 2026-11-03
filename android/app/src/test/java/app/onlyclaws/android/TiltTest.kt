package app.onlyclaws.android

import org.junit.Assert.assertEquals
import org.junit.Test
import kotlin.math.abs

class TiltTest {
    @Test
    fun stepMovesPartway() {
        assertEquals(0.2, Tilt.step(0.0, 1.0, 0.2), 1e-9)
        assertEquals(1.0, Tilt.step(1.0, 1.0, 0.2), 1e-9)
    }

    @Test
    fun gravityFlatIsNearZero() {
        val (roll, pitch) = Tilt.fromGravity(0f, 0f, 9.8f)
        assertEquals(0.0, roll, 1e-6)
        assertEquals(0.0, pitch, 1e-6)
    }

    @Test
    fun gravityToTheRightRollsPositive() {
        val (roll, pitch) = Tilt.fromGravity(9.8f, 0f, 0.1f)
        assertTruePositive(roll)
        assertEquals(0.0, pitch, 0.05)
    }

    private fun assertTruePositive(n: Double) {
        if (!(n > 0.5 && abs(n) < 2.0)) throw AssertionError("expected a positive tilt, got $n")
    }
}
