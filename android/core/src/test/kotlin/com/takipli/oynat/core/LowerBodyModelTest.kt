package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class LowerBodyModelTest {
    @Test
    fun smoothsSuddenBoxJitterAndLimitsScalePumping() {
        val model = LowerBodyModel()
        val first = model.update(0.0, doubleArrayOf(0.5, 0.65, 0.30, 0.42), null)
        val second = model.update(1.0 / 30.0, doubleArrayOf(0.5, 0.65, 0.70, 0.80), null)
        val a = assertNotNull(first.anatomical)
        val b = assertNotNull(second.anatomical)
        assertTrue(b[2] < 0.34, "one-frame mask expansion must not cause a zoom jump")
        assertTrue(b[3] < 0.46, "one-frame mask expansion must not cause a zoom jump")
        assertTrue(b[2] > a[2])
    }

    @Test
    fun holdsLastReliableAnatomicalRegionDuringShortOcclusion() {
        val model = LowerBodyModel(holdSeconds = 1.0)
        val first = model.update(0.0, doubleArrayOf(0.48, 0.62, 0.28, 0.40), null, 0.9)
        val lost = model.update(0.4, null, null, 0.0)
        assertNotNull(first.anatomical)
        assertTrue(lost.held)
        assertEquals(first.anatomical!![2], lost.anatomical!![2], 1e-9)
        assertEquals(first.anatomical!![3], lost.anatomical!![3], 1e-9)
    }

    @Test
    fun doesNotHoldIndefinitelyAfterLongLoss() {
        val model = LowerBodyModel(holdSeconds = 0.5)
        model.update(0.0, doubleArrayOf(0.5, 0.6, 0.3, 0.4), null, 0.9)
        val lost = model.update(1.0, null, null, 0.0)
        assertEquals(null, lost.anatomical)
        assertEquals(false, lost.held)
        assertEquals(0.0, lost.confidence)
    }

    @Test
    fun classifiesPostureOnlyAfterHysteresis() {
        val model = LowerBodyModel()
        // Both knees flexed to approximately 90 degrees.
        val seated = MutableList(51) { 0.0 }
        fun joint(i: Int, x: Double, y: Double) { seated[3 * i] = x; seated[3 * i + 1] = y; seated[3 * i + 2] = 0.95 }
        joint(11, 0.4, 0.4); joint(13, 0.4, 0.6); joint(15, 0.6, 0.6)
        joint(12, 0.6, 0.4); joint(14, 0.6, 0.6); joint(16, 0.8, 0.6)
        assertEquals(LowerBodyPosture.UNKNOWN, model.update(0.0, doubleArrayOf(0.5, 0.6, 0.3, 0.4), seated).posture)
        model.update(0.1, doubleArrayOf(0.5, 0.6, 0.3, 0.4), seated)
        assertEquals(LowerBodyPosture.SEATED, model.update(0.2, doubleArrayOf(0.5, 0.6, 0.3, 0.4), seated).posture)
    }
}
