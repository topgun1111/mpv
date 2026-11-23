package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class SamAdaptiveSmoothingTest {
    private fun row(
        x: Double,
        y: Double = 0.5,
        c: Double = 0.95,
        w: Double = 0.40,
        h: Double = 0.40,
    ): List<Double> = listOf(x, y, c, w, h)

    private fun ts(n: Int, fps: Double = 10.0): List<Double> =
        (0 until n).map { it / fps }

    @Test fun reducesSmallAlternatingJitterWithoutChangingAveragePosition() {
        val data = (0 until 21).map { i ->
            row(0.5 + if (i % 2 == 0) 0.002 else -0.002)
        }
        val out = SamAdaptiveSmoothing.smooth(data, ts(data.size), aspect = 16.0 / 9.0)
        val originalError = (1 until 20).sumOf { abs(data[it][0] - 0.5) }
        val filteredError = (1 until 20).sumOf { abs(out[it][0] - 0.5) }
        assertTrue(filteredError < originalError * 0.65, "stationary jitter not attenuated enough")
        assertEquals(data.first(), out.first())
        assertEquals(data.last(), out.last())
    }

    @Test fun smoothLinearFastPanStaysAtExactMeasuredPosition() {
        val data = (0..8).map { row(0.15 + 0.08 * it) }
        val out = SamAdaptiveSmoothing.smooth(data, ts(data.size), aspect = 16.0 / 9.0)
        assertEquals(data, out) // a constant-speed pan has zero curvature, so no lag
    }

    @Test fun abruptPanAndSharpReversalPreserved() {
        val data = listOf(
            row(0.2), row(0.2), row(0.45), row(0.7), row(0.7),
            row(0.4), row(0.2), row(0.2),
        )
        val out = SamAdaptiveSmoothing.smooth(data, ts(data.size), aspect = 16.0 / 9.0)
        assertEquals(data, out)
    }

    @Test fun lowMotionIsSmoothedButGenuineReversalRemains() {
        val data = listOf(
            row(0.500), row(0.502), row(0.498), row(0.500),
            row(0.55), row(0.60), row(0.54), row(0.50),
        )
        val out = SamAdaptiveSmoothing.smooth(data, ts(data.size))
        assertTrue(out[1][0] < data[1][0])
        assertTrue(out[2][0] > data[2][0])
        assertEquals(data[5], out[5]) // meaningful turning point not smoothed
    }

    @Test fun noBridgingAcrossTrackingLossOrLargeTimeGap() {
        val data = listOf(row(0.4), row(0.41), emptyList(), row(0.45), row(0.46))
        assertEquals(data, SamAdaptiveSmoothing.smooth(data, ts(data.size)))
        val gap = listOf(row(0.4), row(0.406), row(0.4))
        assertEquals(gap, SamAdaptiveSmoothing.smooth(gap, listOf(0.0, 0.1, 0.75)))
    }

    @Test fun preservesPickRowConfidenceAndMaskSizeExactly() {
        val data = listOf(
            row(0.40, c = 0.7, w = 0.2, h = 0.3),
            row(0.404, c = 0.8, w = 0.25, h = 0.34),
            row(0.40, c = 0.9, w = 0.3, h = 0.36),
            row(0.404, c = 0.75, w = 0.35, h = 0.38),
            row(0.40, c = 0.65, w = 0.4, h = 0.39),
        )
        val out = SamAdaptiveSmoothing.smooth(data, ts(data.size), pickedIndex = 2)
        assertEquals(data[2], out[2])
        for (i in data.indices) assertEquals(data[i].drop(2), out[i].drop(2))
        assertTrue(out[1][0] < data[1][0])
        assertTrue(out[3][0] < data[3][0])
    }

    @Test fun respectsIrregularSamplingInterval() {
        val values = listOf(row(0.2), row(0.303), row(0.5))
        val out = SamAdaptiveSmoothing.smooth(values, listOf(0.0, 0.1, 0.3), aspect = 1.0)
        // At t=0.1 the linear trajectory's value is 0.3, not midpoint 0.35.
        assertTrue(out[1][0] < values[1][0])
        assertTrue(out[1][0] > 0.299)
    }

    @Test fun lowConfidenceAndMalformedSamplesStayUntouched() {
        val values = listOf(row(0.4), row(0.408, c = 0.2), row(0.4))
        assertEquals(values, SamAdaptiveSmoothing.smooth(values, ts(3)))
        val malformed = listOf(row(0.4), row(Double.NaN), row(0.4))
        val out = SamAdaptiveSmoothing.smooth(malformed, ts(3))
        assertTrue(out[1][0].isNaN())
        assertEquals(malformed[0], out[0]); assertEquals(malformed[2], out[2])
        assertEquals(values, SamAdaptiveSmoothing.smooth(values, listOf(0.0, 0.1)))
        assertEquals(values, SamAdaptiveSmoothing.smooth(values, ts(3), aspect = Double.NaN))
        assertFalse(SamAdaptiveSmoothing.smooth(emptyList(), emptyList()).isNotEmpty())
    }
}
