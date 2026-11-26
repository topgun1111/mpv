package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class GradeTest {
    @Test fun defaultsAndRanges() {
        val g = Grade()
        assertTrue(g.neutral())
        assertEquals(11, g.uniforms().size)
        assertTrue(g.uniforms().all { it == 0f })
        for (c in GradeControl.entries) {
            assertEquals(c.min, g.with(c, Int.MIN_VALUE)[c])
            assertEquals(c.max, g.with(c, Int.MAX_VALUE)[c])
        }
        assertEquals(0, g[GradeControl.HAZE])
    }

    @Test fun windowsPresetsAndUniformOrder() {
        val g = HazePreset.MODERATE.grade
        assertEquals(16, g[GradeControl.HAZE])
        assertEquals(10, g[GradeControl.SATURATION])
        assertEquals(-5, g[GradeControl.HIGHLIGHTS])
        assertEquals(0.16f, g.uniforms()[0])
        assertEquals(0.25f, g.uniforms()[8])
        assertEquals(0.15f, g.uniforms()[9])
        assertEquals(0f, g.uniforms()[10])
    }

    @Test fun bitrateLimitsAndOrder() {
        val b = 20_000_000
        assertEquals(32_000_000, gradeBitrate(b, GradeQuality.MAXIMUM, 20))
        assertEquals(20_000_000, gradeBitrate(b, GradeQuality.HIGH, 20))
        assertEquals(13_000_000, gradeBitrate(b, GradeQuality.BALANCED, 20))
        assertEquals(7_000_000, gradeBitrate(b, GradeQuality.SMALL, 20))
        assertEquals(2_000_000, gradeBitrate(0, GradeQuality.SMALL, 0))
        assertEquals(100_000_000, gradeBitrate(Int.MAX_VALUE, GradeQuality.MAXIMUM, 0))
        assertEquals(2_000_000, gradeBitrate(b, GradeQuality.CUSTOM, -1))
        assertEquals(100_000_000, gradeBitrate(b, GradeQuality.CUSTOM, Int.MAX_VALUE))
    }
}
