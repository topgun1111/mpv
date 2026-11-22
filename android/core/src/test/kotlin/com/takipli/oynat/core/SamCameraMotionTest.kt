package com.takipli.oynat.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class SamCameraMotionTest {
    private fun near(expected: Double, actual: Double, tol: Double = 1e-9) {
        kotlin.test.assertTrue(abs(expected - actual) <= tol, "expected $expected, actual $actual")
    }

    private fun rotated(theta: Double, w: Int, h: Int, tx: Double = 0.0, ty: Double = 0.0): DoubleArray {
        val a = cos(theta); val b = sin(theta)
        val cx = w / 2.0; val cy = h / 2.0
        return doubleArrayOf(
            a, -b, cx - a * cx + b * cy + tx,
            b, a, cy - b * cx - a * cy + ty,
            0.0, 0.0, 1.0,
        )
    }

    @Test fun rotationOnWideVideoProjectsCenterAndReverses() {
        val motion = SamCameraMotion(listOf(null, rotated(PI / 6, 1920, 1080)), 1920, 1080)
        val f = assertNotNull(motion.project(0.65, 0.5, 0, 1))
        near(0.5 + 0.15 * cos(PI / 6), f[0]); near(0.5 + 0.15 * 1920 / 1080 * sin(PI / 6), f[1])
        val back = assertNotNull(motion.project(f[0], f[1], 1, 0))
        near(0.65, back[0]); near(0.5, back[1])
    }

    @Test fun projectedBoundsEnvelopeContainsRotatedCorners() {
        val motion = SamCameraMotion(listOf(null, rotated(PI / 4, 1000, 1000)), 1000, 1000)
        val b = assertNotNull(motion.projectBounds(0.4, 0.4, 0.6, 0.6, 0, 1))
        val half = 0.1 * kotlin.math.sqrt(2.0)
        near(0.5 - half, b[0]); near(0.5 - half, b[1])
        near(0.5 + half, b[2]); near(0.5 + half, b[3])
    }

    @Test fun translationAndZoomOnlyGuideThePosition() {
        val matrix = doubleArrayOf(1.05, 0.0, 12.0, 0.0, 1.05, -6.0, 0.0, 0.0, 1.0)
        val motion = SamCameraMotion(listOf(null, matrix), 1200, 800)
        val f = assertNotNull(motion.project(0.5, 0.25, 0, 1))
        near(0.535, f[0]); near(0.255, f[1])
        val reverse = assertNotNull(motion.project(f[0], f[1], 1, 0))
        near(0.5, reverse[0]); near(0.25, reverse[1])
        near(1.05, assertNotNull(motion.scale(0, 1)))
        near(1.0 / 1.05, assertNotNull(motion.scale(1, 0)))
    }

    @Test fun unsafeMissingOrNonAdjacentEstimatesDoNotMoveTarget() {
        val good = rotated(PI / 12, 1000, 800)
        val invalid = doubleArrayOf(1.0, 0.0, Double.NaN, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        val motion = SamCameraMotion(listOf(null, good, null, invalid), 1000, 800)
        assertNull(motion.project(0.5, 0.5, 1, 2))
        assertNull(motion.scale(1, 2))
        assertNull(motion.project(0.5, 0.5, 0, 2))
        assertNull(motion.scale(0, 2))
        assertNull(motion.project(0.5, 0.5, 2, 3))
        assertEquals(listOf(0.5, 0.5), assertNotNull(motion.project(0.5, 0.5, 1, 1)).toList())
        val hugeRoll = SamCameraMotion(listOf(null, rotated(PI * 0.8, 1000, 800)), 1000, 800)
        assertNull(hugeRoll.project(0.5, 0.5, 0, 1))
        assertNull(hugeRoll.scale(0, 1))
    }
}
