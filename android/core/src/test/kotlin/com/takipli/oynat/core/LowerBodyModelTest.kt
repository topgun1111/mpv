package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LowerBodyModelTest {
    private fun seated(): List<Double> {
        val row = MutableList(51) { 0.0 }
        fun set(j: Int, x: Double, y: Double, c: Double) {
            row[3 * j] = x; row[3 * j + 1] = y; row[3 * j + 2] = c
        }
        set(5, 0.4, 0.25, 0.9); set(6, 0.6, 0.25, 0.9)
        set(11, 0.42, 0.55, 0.8); set(12, 0.58, 0.55, 0.8)
        // Low-confidence, implausibly distant joints represent desk hallucinations.
        set(13, 0.45, 1.05, 0.5); set(15, 0.45, 1.4, 0.5)
        return row
    }

    @Test
    fun frontalUpwardProfileKeepsAnatomicalAndVisibleRegionsSeparate() {
        val e = assertNotNull(estimateLowerBody(seated(), 1000, 1000, 500.0, deskOcclusionY = 0.72))
        assertEquals(LowerBodyCameraProfile.FRONTAL_SLIGHT_UP, e.cameraProfile)
        assertTrue(e.inferred)
        assertNotNull(e.visibleBox)
        assertTrue(e.anatomicalBox[3] > e.visibleBox!![3])
        assertEquals(0.7, e.anatomicalBox[1], 1e-9)
    }

    @Test
    fun noBoundaryLeavesVisibleRegionEqualToAnatomicalRegion() {
        val e = assertNotNull(estimateLowerBody(seated(), 1000, 1000, 500.0))
        assertContentEquals(e.anatomicalBox, assertNotNull(e.visibleBox))
    }

    @Test
    fun invalidInputAndNonLegPresetAreRejected() {
        assertNull(estimateLowerBody(null, 1000, 1000, 500.0))
        assertNull(estimateLowerBody(seated(), 1000, 1000, 500.0, preset = "torso"))
    }

    @Test
    fun temporalFilterHoldsBriefOcclusionThenExpiresAndResets() {
        val e = assertNotNull(estimateLowerBody(seated(), 1000, 1000, 500.0))
        val f = LowerBodyTemporalFilter(smoothing = 0.5, maxMissingFrames = 2)
        val first = assertNotNull(f.update(e))
        val second = assertNotNull(f.update(null))
        assertContentEquals(first, second)
        assertNotNull(f.update(null))
        assertNull(f.update(null))
        assertNotNull(f.update(e))
        f.reset()
        assertNull(f.update(null))
    }
}
