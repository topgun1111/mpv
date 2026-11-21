package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Deterministic offline fixtures: no neural inference is simulated by these tests. */
class OcclusionRegressionTest {
    private fun row(id: Int) = listOf(id.toDouble(), 0.30, 0.40, 0.38, 0.50, 0.9)

    @Test fun eightSecondRecoveryWindowDoesNotInterruptAShortBlock() {
        val w = LostWatch(alertS = 8.0)
        assertFalse(w.update(0.0, true))
        for (i in 1..70) assertFalse(w.update(i * 0.1, false))
        assertFalse(w.update(7.1, true)) // the original target returned on its own
    }

    @Test fun backwardsAndForwardsAssociationPreservesZoomAcrossAThreeSecondOcclusion() {
        val samples = (0..100).map { i ->
            val detection = when (i) {
                in 0..20 -> listOf(row(1))
                in 51..100 -> listOf(row(2))
                else -> emptyList()
            }
            Sample(i * 0.1, d = detection)
        }
        val sameClothes = List(APPEARANCE_BINS) { if (it % 8 == 2) 1.0 else 0.0 }
        val doc = TrackDoc(2, VideoInfo(w = 1000, h = 1000), samples = samples,
            appearance = mapOf("1" to sameClothes, "2" to sameClothes))
        val views = buildTargetViews(doc, Target(2), Config(lostBridgeS = 4.0), robust = true)
        fun zoom(t: Double) = views.minBy { abs(it[0] - t) }[1]
        assertTrue(zoom(1.5) > 0.5, "target before the pick must be recovered")
        assertTrue(zoom(3.5) > 0.5, "zoom must not collapse during a short block")
        assertTrue(abs(zoom(3.5) - zoom(5.5)) < 0.4, "gap should preserve apparent target size")
        val stats = occlusionStats(doc.copy(target = Target(2)))
        assertTrue(stats.absentRuns >= 1)
        assertTrue(stats.longestAbsentS >= 2.9)
        assertTrue(stats.linkedIds >= 1)
    }
}
