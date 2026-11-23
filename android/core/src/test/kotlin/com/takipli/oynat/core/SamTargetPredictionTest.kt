package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SamTargetPredictionTest {
    private fun motion(n: Int = 32, dx: Double = 0.0): SamCameraMotion =
        SamCameraMotion(List(n) { i ->
            if (i == 0) null else doubleArrayOf(1.0, 0.0, dx, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        }, 1000, 800)

    @Test fun targetMotionAddsVelocityAboveCameraOnlyProjection() {
        val p = SamTargetPrediction(); val cam = motion()
        p.seed(0, 0.20, 0.50)
        assertEquals(0.20, assertNotNull(p.advance(1, cam))[0], 1e-9)
        p.observe(0.25, 0.50, true)
        val next = assertNotNull(p.advance(2, cam))
        assertTrue(next[0] > 0.27 && next[0] < 0.30)
        p.observe(0.30, 0.50, true)
        assertTrue(assertNotNull(p.advance(3, cam))[0] > 0.33)
    }

    @Test fun directionReversalCancelsOldMomentumQuickly() {
        val p = SamTargetPrediction(); val cam = motion()
        p.seed(0, 0.20, 0.50)
        assertNotNull(p.advance(1, cam)); p.observe(0.25, 0.50, true)
        assertNotNull(p.advance(2, cam)); p.observe(0.30, 0.50, true)
        assertNotNull(p.advance(3, cam)); p.observe(0.27, 0.50, true)
        val result = assertNotNull(p.advance(4, cam))
        assertTrue(result[0] < 0.27 && result[0] > 0.23)
    }

    @Test fun shortLossesDampenResidualMotionThenStopIt() {
        val p = SamTargetPrediction(); val cam = motion()
        p.seed(0, 0.25, 0.40)
        assertNotNull(p.advance(1, cam)); p.observe(0.34, 0.40, true)
        val a = assertNotNull(p.advance(2, cam))[0]
        val b = assertNotNull(p.advance(3, cam))[0]
        val c = assertNotNull(p.advance(4, cam))[0]
        val d = assertNotNull(p.advance(5, cam))[0]
        assertTrue(a > 0.34 && b > a && c > b)
        assertEquals(c, d, 1e-9)
        repeat(20) { assertEquals(d, assertNotNull(p.advance(6 + it, cam))[0], 1e-9) }
    }

    @Test fun cameraTranslationAloneDoesNotLearnTargetMotion() {
        val p = SamTargetPrediction(); val cam = motion(dx = 30.0)
        p.seed(0, 0.20, 0.50)
        assertEquals(0.23, assertNotNull(p.advance(1, cam))[0], 1e-9)
        p.observe(0.23, 0.50, true)
        assertEquals(0.26, assertNotNull(p.advance(2, cam))[0], 1e-9)
    }

    @Test fun coveredMaskAndReappearanceResetVelocity() {
        val p = SamTargetPrediction(); val cam = motion()
        p.seed(0, 0.20, 0.50)
        assertNotNull(p.advance(1, cam)); p.observe(0.28, 0.50, false)
        assertEquals(0.28, assertNotNull(p.advance(2, cam))[0], 1e-9)
        assertNotNull(p.advance(3, cam))
        p.observe(0.38, 0.50, true)
        assertEquals(0.38, assertNotNull(p.advance(4, cam))[0], 1e-9)
    }

    @Test fun invalidCameraChainDisablesPredictionUntilNewMask() {
        val p = SamTargetPrediction()
        val good = doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        val cam = SamCameraMotion(listOf(null, good, null, good, good), 1000, 800)
        p.seed(0, 0.20, 0.50)
        assertNotNull(p.advance(1, cam)); p.observe(0.25, 0.50, true)
        assertNull(p.advance(2, cam))
        assertNull(p.advance(3, cam))
        p.observe(0.31, 0.50, true)
        assertEquals(0.31, assertNotNull(p.advance(4, cam))[0], 1e-9)
    }

    @Test fun reverseOrderAndSkippedIndices() {
        val p = SamTargetPrediction(); val cam = motion()
        p.seed(4, 0.60, 0.40)
        assertNotNull(p.advance(3, cam)); p.observe(0.55, 0.40, true)
        assertTrue(assertNotNull(p.advance(2, cam))[0] < 0.55)
        assertNull(p.advance(0, cam))
        assertNull(p.advance(1, cam))
        p.observe(0.30, 0.40, true)
        assertNotNull(p.advance(2, cam))
    }

    @Test fun invalidAndEdgeCoordinatesCannotEscapeTheImage() {
        val p = SamTargetPrediction(); val cam = motion()
        assertFailsWith<IllegalArgumentException> { p.seed(0, Double.NaN, 0.5) }
        assertFailsWith<IllegalArgumentException> { p.seed(-1, 0.3, 0.5) }
        p.seed(0, 0.98, 0.5)
        assertNotNull(p.advance(1, cam)); p.observe(1.0, 0.5, true)
        repeat(20) {
            val q = assertNotNull(p.advance(2 + it, cam))
            assertTrue(q[0] in 0.0..1.0 && q[1] in 0.0..1.0)
        }
    }
}
