package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Occlusion hardening of the pose path: ID re-link after a long block, ignoring an ID that teleports onto a blocker. */
class RelinkTest {
    private val n = 100
    private fun row(id: Int, cx: Double, cy: Double = 0.5, h: Double = 0.10) = listOf(id.toDouble(), cx - 0.02, cy - h / 2, cx + 0.02, cy + h / 2, 0.9)

    /** `rows[i]` = detections of sample i; ids are tracked in `present`. */
    private fun doc(cutAt: Int? = null, f: (Int) -> List<List<Double>>) =
        TrackDoc(version = 2, video = VideoInfo(w = 1000, h = 1000), samples = (0 until n).map { Sample(it * 0.1, d = f(it), cut = if (it == cutAt) 1 else null) })

    // ID 1 at (0.3, 0.5) for samples 0..29, blocked 3.1 s, then the same person is ID 2 from sample 60. ID 3 stands still the whole time.
    private fun scene(newX: Double = 0.32, newY: Double = 0.5, cutAt: Int? = null) = doc(cutAt) { i ->
        buildList {
            if (i < 30) add(row(1, 0.3))
            if (i >= 60) add(row(2, newX, newY))
            add(row(3, 0.8))
        }
    }

    @Test fun newIdWhereTheTargetVanishedIsLinked() {
        assertEquals(setOf(1, 2), relinkIds(scene(), setOf(1)))
        assertEquals(Target(1, linked = listOf(2)), relinkTarget(scene(), Target(1)))
    }

    @Test fun farAwayNewcomerOrCutOrLateIdIsNotLinked() {
        assertEquals(setOf(1), relinkIds(scene(newX = 0.9, newY = 0.1), setOf(1)))
        assertEquals(setOf(1), relinkIds(scene(cutAt = 45), setOf(1)))
        assertEquals(setOf(1), relinkIds(scene(), setOf(1), windowS = 2.0)) // blocked 3.1 s > window
        assertEquals(setOf(3), relinkIds(scene(), setOf(3)))               // never vanished: nothing to continue
    }

    @Test fun chainOfTwoBlocks() {
        val d = doc { i -> buildList { if (i < 20) add(row(1, 0.3)); if (i in 40..59) add(row(2, 0.31)); if (i >= 80) add(row(5, 0.33)) } }
        assertEquals(setOf(1, 2, 5), relinkIds(d, setOf(1)))
    }

    @Test fun viewsKeepZoomAfterTheBlockOnlyWhenRobust() {
        val d = scene()
        val cfg = Config(lostBridgeS = 0.0)
        fun zoomAt(v: List<ViewKey>, t: Double) = v.minByOrNull { Math.abs(it[0] - t) }!![1]
        val plain = buildTargetViews(d, Target(1), cfg)
        val robust = buildTargetViews(d, Target(1), cfg, robust = true)
        assertTrue(zoomAt(plain, 9.0) < 0.1)    // the old ID never comes back: zoomed out for the rest of the clip
        assertTrue(zoomAt(robust, 9.0) > 1.0)   // linked to ID 2: still following, zoomed in
    }

    @Test fun teleportingIdIsIgnoredButAPermanentMoveIsAccepted() {
        // samples 20..22 the ID sits on a blocker at x = 0.8, then it is back
        val stolen = doc { i -> listOf(row(1, if (i in 20..22) 0.8 else 0.3)) }
        assertEquals(setOf(20, 21, 22), suspectSamples(stolen, setOf(1)))
        // from sample 20 on it really is somewhere else for good: after 8 samples in a row it is accepted
        val moved = doc { i -> listOf(row(1, if (i >= 20) 0.8 else 0.3)) }
        assertEquals((20..26).toSet(), suspectSamples(moved, setOf(1)))
        // a person running fast (0.5 height per sample) is never suspect
        val fast = doc { i -> listOf(row(1, 0.1 + 0.002 * i)) }
        assertTrue(suspectSamples(fast, setOf(1)).isEmpty())
    }

    @Test fun stolenSamplesDoNotMoveTheCameraWhenRobust() {
        val stolen = doc { i -> listOf(row(1, if (i in 20..22) 0.8 else 0.3)) }
        val cfg = Config()
        fun panRange(v: List<ViewKey>) = v.maxOf { it[2] } - v.minOf { it[2] }
        val plain = buildTargetViews(stolen, Target(1), cfg)
        val robust = buildTargetViews(stolen, Target(1), cfg, robust = true)
        assertTrue(panRange(plain) > panRange(robust) + 0.05, "plain ${panRange(plain)} robust ${panRange(robust)}") // the plain camera swings to the blocker
    }
}
