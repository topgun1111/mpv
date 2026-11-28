package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
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
        val source = 20_000_000
        assertEquals(source, gradeBitrate(source, GradeQuality.SOURCE, 0))
        assertEquals(25_000_000, gradeBitrate(source, GradeQuality.HIGH, 0))
        assertEquals(32_000_000, gradeBitrate(source, GradeQuality.MAXIMUM, 0))
        assertEquals(source, gradeBitrate(source, GradeQuality.CUSTOM, -1))
        assertEquals(35_000_000, gradeBitrate(source, GradeQuality.CUSTOM, 35))
        assertEquals(120_000_000, gradeBitrate(120_000_000, GradeQuality.CUSTOM, 100))
        assertEquals(192_000_000, gradeBitrate(120_000_000, GradeQuality.MAXIMUM, 0))
        assertEquals(Int.MAX_VALUE, gradeBitrate(Int.MAX_VALUE, GradeQuality.MAXIMUM, 0))
        assertEquals(Int.MAX_VALUE, gradeBitrate(source, GradeQuality.CUSTOM, Int.MAX_VALUE))
        assertFailsWith<IllegalArgumentException> { gradeBitrate(0, GradeQuality.SOURCE, 0) }
    }
}
