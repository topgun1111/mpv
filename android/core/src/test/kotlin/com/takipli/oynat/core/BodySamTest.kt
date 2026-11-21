package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class BodySamTest {
    private val target = Target(1, preset = "left_leg")

    private fun sample(t: Double, knee: Boolean): Sample {
        val kp = MutableList(3 * N_KPT) { 0.0 }
        fun joint(i: Int, x: Double, y: Double, confidence: Double) {
            kp[3 * i] = x; kp[3 * i + 1] = y; kp[3 * i + 2] = confidence
        }
        joint(11, 0.45, 0.48, 0.9) // hip remains visible even during knee occlusion
        if (knee) joint(13, 0.47, 0.68, 0.9)
        return Sample(t, d = listOf(listOf(1.0, 0.2, 0.1, 0.8, 0.95, 0.9)), kp = mapOf("1" to kp))
    }

    @Test fun promptsSamWhenDistalLegIsHiddenAlthoughHipIsVisible() {
        val doc = TrackDoc(2, VideoInfo(w = 1000, h = 1000), samples = listOf(sample(0.0, true), sample(0.2, false)))
        assertTrue(bodyPartVisible(doc.samples[0], target, Config()))
        assertFalse(bodyPartVisible(doc.samples[1], target, Config()))
        assertTrue(needsBodySam(doc, target, Config()))
        val seed = assertNotNull(bodySamSeed(doc, target, 0.0, Config()))
        assertTrue(seed.shapes.single().size == 4)
        assertEquals(0.0, seed.t)
    }

    @Test fun samFillsWeakPoseButCannotReplaceReliableJointOrJumpToAnotherPerson() {
        val frames = listOf(sample(0.0, true), sample(0.1, false), sample(0.2, true), sample(0.3, false))
        val pt = PointTrack(a = listOf(
            listOf(0.46, 0.7, 0.9, 0.1, 0.25),
            listOf(0.48, 0.7, 0.9, 0.1, 0.25),
            listOf(0.50, 0.7, 0.9, 0.1, 0.25),
            listOf(0.95, 0.1, 0.9, 0.1, 0.25), // implausible ID switch
        ))
        val doc = TrackDoc(2, VideoInfo(w = 1000, h = 1000), samples = frames, pt = pt)
        val pose = mapOf(0 to doubleArrayOf(0.46, 0.7, 0.10, 0.25), 2 to doubleArrayOf(0.50, 0.7, 0.10, 0.25))
        val fused = fuseBodySam(doc, target, pose, Config(), pickT = 0.0)
        assertEquals(0.48, fused.getValue(1)[0], 1e-9)
        assertEquals(0.50, fused.getValue(2)[0], 1e-9) // reliable pose wins
        assertFalse(3 in fused, "a distant mask must not silently steal the target")
    }

    @Test fun recoveryOnlyPlansShortInternalGaps() {
        val samples = (0..110).map { i ->
            sample(i / 10.0, knee = i in 10..19 || i in 29..59 || i in 65..89 || i in 95..100)
        }
        val doc = TrackDoc(2, VideoInfo(w = 1000, h = 1000), samples = samples)
        val windows = bodySamWindows(doc, target, 5.0, Config())
        assertEquals(2, windows.size)
        assertTrue(windows.all { it.endS - it.startS <= 4.0 })
        assertTrue(windows.all { it.seed.t in 1.9..9.4 })
        assertTrue(windows.any { it.seed.t == 5.9 })
        assertTrue(windows.any { it.seed.t == 1.9 })
        // Missing keypoints at the beginning and end cannot seed a safe pass.
        assertTrue(windows.none { it.startS < 1.0 || it.endS > 10.0 })
    }

    @Test fun recoveryNeverCrossesCutsOrLongOcclusions() {
        val frames = (0..80).map { i ->
            sample(i / 10.0, knee = i in 0..10 || i in 55..60 || i in 65..80)
                .copy(cut = if (i == 63) 1 else 0)
        }
        val doc = TrackDoc(2, VideoInfo(w = 1000, h = 1000), samples = frames)
        assertTrue(bodySamWindows(doc, target, 1.0, Config()).isEmpty())
    }
}
