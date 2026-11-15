package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class RecordTest {
    @Test
    fun pinchDoublesScale() {
        val v = applyGesture(View(0.0, 0.0, 0.0), 0.0, 0.0, 2.0, 3.5)
        assertEquals(1.0, v.zoom, 1e-9)
        assertEquals(0.0, applyGesture(v, 0.0, 0.0, 0.5, 3.5).zoom, 1e-9)
        assertEquals(0.0, applyGesture(v, 0.0, 0.0, 0.1, 3.5).zoom, 1e-9) // 1x altına inmez
        assertEquals(3.5, applyGesture(v, 0.0, 0.0, 1000.0, 3.5).zoom, 1e-9)
    }

    @Test
    fun dragMovesContentWithFinger() {
        val z1 = View(1.0, 0.0, 0.0) // 2x: yüzeyin %20'si = karenin %10'u
        val v = applyGesture(z1, 0.2, -0.2, 1.0, 3.5)
        assertEquals(0.1, v.panX, 1e-9); assertEquals(-0.1, v.panY, 1e-9)
        // pan kare dışına taşmaz: 2x'te en çok 0.25
        val w = applyGesture(z1, 5.0, 5.0, 1.0, 3.5)
        assertEquals(0.25, w.panX, 1e-9); assertEquals(0.25, w.panY, 1e-9)
        // 1x'te kaydıracak yer yok
        val u = applyGesture(View(0.0, 0.0, 0.0), 0.3, 0.3, 1.0, 3.5)
        assertEquals(0.0, u.panX, 1e-9)
    }

    @Test
    fun mergeReplacesOnlyTheRecordedRange() {
        val auto: List<ViewKey> = listOf(listOf(0.0, 0.5, 0.0, 0.0), listOf(5.0, 0.5, 0.0, 0.0), listOf(10.0, 0.5, 0.0, 0.0))
        val seg = RecSeg(2.0, 6.0, listOf(listOf(2.0, 1.0, 0.1, 0.0), listOf(4.0, 1.5, 0.1, 0.0), listOf(6.0, 1.5, 0.1, 0.0)))
        val m = mergeSegment(auto, seg)
        assertEquals(listOf(0.0, 2.0, 4.0, 6.0, 10.0), m.map { it[0] }) // 5.0 silindi
        assertEquals(1.5, viewAt(m, 5.0).zoom, 1e-9)
        assertEquals(auto, mergeSegment(auto, RecSeg(0.0, 1.0, emptyList()))) // boş kayıt değişiklik yapmaz
        // iki parça sırayla işlenir; sonraki öncekinin üstüne yazar
        val m2 = mergeSegments(auto, listOf(seg, RecSeg(3.0, 4.0, listOf(listOf(3.0, 2.0, 0.0, 0.0)))))
        assertTrue(m2.any { it[0] == 3.0 } && m2.none { it[0] == 4.0 })
    }

    @Test
    fun appendKeySkipsTooCloseTimes() {
        var k = appendKey(emptyList(), 1.0, View(1.0, 0.0, 0.0))
        k = appendKey(k, 1.01, View(1.0, 0.0, 0.0))
        k = appendKey(k, 0.5, View(1.0, 0.0, 0.0)) // geri sarma
        k = appendKey(k, 1.05, View(1.2, 0.0, 0.0))
        assertEquals(listOf(1.0, 1.05), k.map { it[0] })
    }
}
