package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class FreePointTest {
    // 20 samples at 10 fps; person (id 1) walks right, the tapped spot is its torso: x = 0.3 + 0.02 i, y = 0.5.
    private fun doc(pass: List<List<Double>>): TrackDoc {
        val samples = (0 until 20).map { i ->
            val cx = 0.3 + 0.02 * i
            Sample(i / 10.0, listOf(listOf(1.0, cx - 0.1, 0.2, cx + 0.1, 0.9, 0.9)))
        }
        return TrackDoc(2, VideoInfo(w = 1920, h = 1080, fps = 30.0), 10.0, samples, pt = PointTrack(a = pass))
    }

    private fun pass(): List<List<Double>> = (0 until 20).map { i ->
        when (i) {
            5 -> listOf(0.9, 0.1, 0.9)         // tracker jumped to the background
            8, 9 -> emptyList()                // lost (blur / fast motion)
            else -> listOf(0.3 + 0.02 * i, 0.5, 0.9)
        }
    }

    private val pick = FreePick(t = 0.0, x = 0.3, y = 0.5, id = 1)

    @Test
    fun jumpIsRejectedAndLossIsFilledFromAnchor() {
        val f = fuseFreePoint(doc(pass()), pick, Config())
        assertTrue(abs(f.getValue(5)[0] - 0.4) < 0.01 && abs(f.getValue(5)[1] - 0.5) < 0.01)
        for (i in listOf(8, 9)) assertTrue(abs(f.getValue(i)[0] - (0.3 + 0.02 * i)) < 0.01, "sample $i")
        assertEquals(20, f.size)
    }

    @Test
    fun targetWithFreePickBuildsViewsAtChosenZoom() {
        val d = doc(pass())
        val views = buildTargetViews(d, Target(id = 1, free = pick.copy(zoom = 1.5)), Config())
        assertTrue(views.isNotEmpty())
        val mid = views.minByOrNull { abs(it[0] - 1.0) }!!
        assertEquals(1.5, mid[1], 1e-3)
        assertNotNull(viewAtSmooth(views, 0.95))
    }

    @Test
    fun smoothSamplingHitsKeysAndDoesNotOvershoot() {
        val keys: List<ViewKey> = listOf(listOf(0.0, 1.0, 0.0, 0.0), listOf(1.0, 1.0, 0.2, 0.0), listOf(2.0, 1.0, 0.2, 0.0), listOf(3.0, 1.0, 0.4, 0.0))
        assertEquals(0.2, viewAtSmooth(keys, 1.0).panX, 1e-9)
        var prev = -1.0
        for (k in 0..300) {
            val x = viewAtSmooth(keys, k / 100.0).panX
            assertTrue(x in -1e-9..0.4 + 1e-9 && x >= prev - 1e-9, "t=${k / 100.0} x=$x")
            prev = x
        }
    }
}

class FreePickResolveTest {
    @Test
    fun freePickBecomesFreeTargetEvenWithoutPerson() {
        val d = TrackDoc(2, VideoInfo(w = 1920, h = 1080, fps = 30.0), 10.0, listOf(Sample(0.0)))
        val t = resolvePick(d, TargetPick(0.0, 0.5, 0.5, free = true, zoom = 2.0), Config())
        assertNotNull(t); assertEquals(-1, t.id); assertEquals(2.0, t.free?.zoom)
    }
}

class PinTest {
    private val pick = FreePick(t = 0.0, x = 0.3, y = 0.5)

    @Test
    fun pinsReplaceNearOnesAndStaySorted() {
        val p = pick.withPin(1.0, 0.5, 0.5, 0.05).withPin(0.5, 0.4, 0.4, 0.05).withPin(1.02, 0.6, 0.6, 0.05)
        assertEquals(listOf(0.5, 1.02), p.pins.map { it[0] })
        assertEquals(0.6, p.pins[1][1])
        assertEquals(1, p.withoutPin(0.5, 0.05).pins.size)
    }

    @Test
    fun pinIsExactAndWeakSamplesAreFound() {
        val samples = (0 until 10).map { Sample(it / 10.0) }
        val d = TrackDoc(2, VideoInfo(w = 1920, h = 1080, fps = 30.0), 10.0, samples)
        val p = pick.withPin(0.5, 0.8, 0.2, 0.05)
        val f = fuseFreePoint(d, p, Config())
        assertEquals(0.8, f.getValue(5)[0], 1e-9); assertEquals(1.0, f.getValue(5)[2])
        val c = freePointConfidence(d, p, Config())
        assertEquals(1.0, c[5]); assertEquals(1, nextWeak(c, 0, +1)?.let { 1 }) // samples without data are weak
        assertEquals(null, nextWeak(doubleArrayOf(1.0, 1.0), 0, +1))
    }
}
