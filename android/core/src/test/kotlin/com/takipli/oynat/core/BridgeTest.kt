package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class BridgeTest {
    private val ts = (0..100).map { it * 0.1 } // 10 s at 10 fps
    // subject visible 0..2.9 s and 6.0..10 s (occluded 3.1 s), same size both times
    private val boxes: Map<Int, DoubleArray> = (0..100).filter { it < 30 || it >= 60 }.associateWith { doubleArrayOf(0.5, 0.5, 0.2, 0.4) }

    private fun zoomAt(v: List<ViewKey>, t: Double) = v.minByOrNull { Math.abs(it[0] - t) }!![1]

    @Test
    fun bridgeKeepsZoomThroughOcclusion() {
        val v = viewsFromBoxes(ts, boxes, Config(lostBridgeS = 6.0))
        val before = zoomAt(v, 2.9)
        assertTrue(before > 0.1)
        for (t in listOf(3.5, 4.5, 5.5)) assertEquals(before, zoomAt(v, t), 0.05)
    }

    @Test
    fun bridgeOffKeepsOldZoomOut() {
        val v = viewsFromBoxes(ts, boxes, Config())
        assertTrue(zoomAt(v, 5.0) < zoomAt(v, 2.9) - 0.1) // old behaviour: zoomed out while lost
    }
}
