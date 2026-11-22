package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class TemporalMemoryTest {
    private fun box(cx: Double, cy: Double = 0.5) = doubleArrayOf(cx, cy, 0.15, 0.2)
    private fun doc(samples: List<Sample>) = TrackDoc(2, VideoInfo(w = 1000, h = 1000), samples = samples)

    @Test fun memorySliderRoundTripsThroughTuning() {
        val cfg = Config(occlusionMemoryS = 2.5)
        val tuning = Tuning.of(cfg)
        assertEquals(2.5, tuning.occlusionMemoryS)
        assertEquals(0.0, cfg.withTuning(tuning.copy(occlusionMemoryS = 0.0)).occlusionMemoryS)
    }

    @Test fun motionContinuesBrieflyAndExpiresWithoutChangingReliableSamples() {
        val d = doc((0..50).map { Sample(it * 0.1) })
        val raw = mapOf(0 to box(0.20), 1 to box(0.22), 40 to box(0.65))
        val predicted = temporalMemoryBoxes(d, raw, holdS = 2.0)
        assertTrue(predicted.getValue(2)[0] > 0.22, "target should keep moving instead of freezing")
        assertEquals(0.2, predicted.getValue(2)[3]) // no zoom-size decay during short absence
        assertTrue(predicted.containsKey(20))
        assertFalse(predicted.containsKey(22), "a long absence must not be filled indefinitely")
        assertEquals(0.65, predicted.getValue(40)[0])
        assertEquals(0.20, raw.getValue(0)[0]) // no mutation of source boxes
        assertTrue(predicted.values.all { box -> box.all { value -> value.isFinite() } })
    }

    @Test fun weakDetectorSliceDoesNotOverwriteRecentLimbMemory() {
        val d = doc((0..45).map { Sample(it * 0.1) })
        val raw = mapOf(0 to box(0.30, 0.72), 1 to box(0.31, 0.72),
            2 to box(0.65, 0.90), 3 to box(0.65, 0.90), 40 to box(0.65, 0.90))
        val remembered = temporalMemoryBoxes(d, raw, holdS = 2.0, weakIndices = setOf(2, 3, 40))
        assertTrue(remembered.getValue(2)[0] < 0.40, "keep the verified foot location, not an arbitrary person slice")
        assertTrue(remembered.getValue(3)[0] < 0.40)
        assertEquals(0.65, remembered.getValue(40)[0], "after expiry, retain fallback rather than guessing")
        assertEquals(0.65, raw.getValue(2)[0])
    }

    @Test fun cameraCompensationMovesPredictionWithTheFrame() {
        val d = doc(listOf(Sample(0.0), Sample(0.1), Sample(0.2, cam = listOf(1.0, 0.0, 0.04, 0.0))))
        val predicted = temporalMemoryBoxes(d, mapOf(0 to box(0.50), 1 to box(0.50)))
        assertTrue(abs(predicted.getValue(2)[0] - 0.54) < 1e-6)
    }

    @Test fun shotCutAndBackwardsTimeResetMemory() {
        val cut = doc(listOf(Sample(0.0), Sample(0.1), Sample(0.2, cut = 1), Sample(0.3)))
        val raw = mapOf(0 to box(0.25), 1 to box(0.26))
        assertFalse(temporalMemoryBoxes(cut, raw).containsKey(2))
        assertFalse(temporalMemoryBoxes(cut, raw).containsKey(3))
        val jump = doc(listOf(Sample(0.0), Sample(0.1), Sample(0.05), Sample(0.2)))
        assertFalse(temporalMemoryBoxes(jump, raw).containsKey(2))
        assertFalse(temporalMemoryBoxes(jump, raw).containsKey(3))
        assertEquals(raw.keys, temporalMemoryBoxes(cut, raw, holdS = 0.0).keys)
    }

    @Test fun robustPartViewsPreferRecentAnatomyOverWeakSlices() {
        fun jointRow(confident: Boolean): List<Double> {
            val row = MutableList(51) { 0.0 }
            if (confident) for ((j, x, y) in listOf(Triple(11, 0.30, 0.40), Triple(13, 0.32, 0.57), Triple(15, 0.33, 0.73))) {
                row[3 * j] = x; row[3 * j + 1] = y; row[3 * j + 2] = 0.95
            }
            return row
        }
        val samples = (0..15).map { i ->
            val person = if (i < 3) listOf(1.0, 0.15, 0.20, 0.48, 0.82, 0.9)
                else listOf(1.0, 0.50, 0.20, 0.83, 0.82, 0.9)
            Sample(i * 0.1, d = listOf(person), kp = mapOf("1" to jointRow(i < 3)))
        }
        val d = doc(samples)
        val cfg = Config(kpRobust = false, kpFilter = false, kpWorld = false)
        val weak = HashSet<Int>()
        presetBoxes(d, setOf(1), "left_foot", cfg, weakFrames = weak)
        assertTrue(4 in weak)
        assertFalse(2 in weak)
        val plain = buildTargetViews(d, Target(1, preset = "left_foot"), cfg)
        val robust = buildTargetViews(d, Target(1, preset = "left_foot"), cfg, robust = true)
        fun panAt(views: List<ViewKey>, t: Double) = views.minBy { abs(it[0] - t) }[2]
        assertTrue(panAt(robust, 0.7) > panAt(plain, 0.7) + 0.1,
            "an occluded foot should not jump toward the detector's generic lower-body slice")
    }
}
