package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class SamScaleMemoryTest {
    private fun near(expected: Double, actual: Double) =
        assertTrue(abs(expected - actual) < 1e-9, "expected $expected, got $actual")

    @Test fun approachingCameraAdjustsExpectedAreaAndRestoresCleanTracking() {
        val s = SamScaleMemory()
        s.seed(0.12, 0.3, 0.4)
        s.advance(1.10)
        val f = 1.075 // bounded 75% of the background scale change
        near(0.3 * f, s.expectedWidth)
        near(0.4 * f, s.expectedHeight)
        near(1.0, s.areaRatio(0.12 * f * f))
        // Clean mask gives the size authority back to SAM, not the background.
        s.observeClean(0.12 * f * f, 0.32, 0.43)
        near(0.32, s.expectedWidth)
        near(0.43, s.expectedHeight)
    }

    @Test fun movingAwayReducesTheFalseOcclusionSignal() {
        val s = SamScaleMemory()
        s.seed(0.10, 0.28, 0.36)
        s.advance(0.90)
        val f = 0.925
        near(1.0, s.areaRatio(0.10 * f * f))
        near(0.28 * f, s.expectedWidth)
        assertTrue(TrackGate.remember(0.8, s.areaRatio(0.10 * f * f)))
    }

    @Test fun smallOccluderMaskKeepsCameraAdjustedCleanBox() {
        val s = SamScaleMemory()
        s.seed(0.16, 0.4, 0.4)
        s.advance(0.9)
        val ratio = s.areaRatio(0.02)
        assertTrue(ratio < TrackGate.PARTIAL_RATIO)
        val (w, h) = TrackGate.size(ratio, 0.08, 0.1, s.expectedWidth, s.expectedHeight)
        near(0.4 * 0.925, w)
        near(0.4 * 0.925, h)
    }

    @Test fun invalidMotionRevertsToLastCleanSizeUntilNextConfirmedMask() {
        val s = SamScaleMemory()
        s.seed(0.10, 0.25, 0.40)
        s.advance(1.10)
        s.advance(null)
        s.advance(1.10) // ignored: no valid chain from the last clean observation
        near(0.25, s.expectedWidth)
        near(0.40, s.expectedHeight)
        near(1.0, s.areaRatio(0.10))
        s.observeClean(0.12, 0.27, 0.42)
        s.advance(1.10)
        near(0.27 * 1.075, s.expectedWidth)
    }

    @Test fun repeatedZoomIsBoundedAndNoisySizesAreRejected() {
        val s = SamScaleMemory()
        s.seed(0.12, 0.31, 0.42)
        repeat(100) { s.advance(1.35) }
        near(0.62, s.expectedWidth) // maximum 2x drift before a new clean mask
        near(0.84, s.expectedHeight)
        assertTrue(s.areaRatio(0.01) < TrackGate.PARTIAL_RATIO)
        s.advance(Double.NaN)
        near(0.31, s.expectedWidth)
        assertFailsWith<IllegalArgumentException> { SamScaleMemory().seed(0.0, 0.4, 0.3) }
        assertFailsWith<IllegalArgumentException> { SamScaleMemory().seed(0.1, Double.NaN, 0.3) }
    }

    @Test fun cleanObservationCannotBeReplacedByInvalidSizes() {
        val s = SamScaleMemory()
        s.seed(0.15, 0.25, 0.35)
        s.observeClean(Double.NaN, 0.8, 0.8)
        s.observeClean(0.1, -1.0, 0.2)
        near(0.25, s.expectedWidth)
        near(0.35, s.expectedHeight)
        assertEquals(0.0, s.areaRatio(Double.NaN))
    }
}
