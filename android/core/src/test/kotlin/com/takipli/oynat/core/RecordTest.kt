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

    @Test
    fun pinchZoomsAboutFingersAndPansTogether() {
        // yalnız taşıma: applyGesture ile aynı
        val a = applyGestureAt(View(1.0, 0.0, 0.0), 0.5, 0.5, 0.2, -0.2, 1.0, 3.5)
        assertEquals(0.1, a.panX, 1e-9); assertEquals(-0.1, a.panY, 1e-9)
        // sağ üst parmakların altındaki nokta zoom'dan sonra da aynı yerde
        val v0 = View(0.0, 0.0, 0.0); val ax = 0.8; val ay = 0.3
        val v1 = applyGestureAt(v0, ax, ay, 0.0, 0.0, 2.0, 3.5)
        assertEquals(1.0, v1.zoom, 1e-9)
        val before = 0.5 + (ax - 0.5) / 1.0; val after = (0.5 - v1.panX) + (ax - 0.5) / 2.0
        assertEquals(before, after, 1e-9)
        // zoom + taşıma aynı anda: nokta parmakla birlikte kayar
        val v2 = applyGestureAt(v0, ax, ay, -0.1, 0.0, 2.0, 3.5)
        val after2 = (0.5 - v2.panX) + (ax - 0.1 - 0.5) / 2.0
        assertEquals(before, after2, 1e-9)
        assertEquals(0.0, applyGestureAt(v1, 0.5, 0.5, 0.0, 0.0, 0.01, 3.5).zoom, 1e-9) // 1x altına inmez
    }

    @Test
    fun speedIsClampedAndSnapped() {
        assertEquals(0.25, clampRecSpeed(0.01), 1e-9)
        assertEquals(2.0, clampRecSpeed(9.0), 1e-9)
        assertEquals(1.0, clampRecSpeed(Double.NaN), 1e-9)
        assertEquals(0.75, clampRecSpeed(0.7499999), 1e-9)
        assertTrue(REC_SPEED_PRESETS.all { clampRecSpeed(it) == it })
    }

    @Test
    fun keyIntervalScalesWithSpeedInVideoTime() {
        assertEquals(0.033, recKeyDt(1.0), 1e-9)
        assertEquals(0.012, recKeyDt(0.25), 1e-9) // 0.25x: video saniyesi 4x yavaş akar, aralık sıkılaşır (alt sınır 12 ms)
        assertEquals(0.066, recKeyDt(2.0), 1e-9)
        // duvar saatinde aralık hızdan bağımsız kalır (alt sınıra takılmadığı sürece)
        assertEquals(recKeyDt(0.5) / 0.5, recKeyDt(1.0) / 1.0, 1e-9)
    }

    @Test
    fun slowRecordingKeepsMoreKeysThanFast() {
        fun count(speed: Double): Int {
            var k: List<ViewKey> = emptyList(); var t = 0.0
            while (t < 2.0) { k = appendKey(k, t, View(0.0, 0.0, 0.0), recKeyDt(speed)); t += 0.034 * speed }
            return k.size
        }
        assertTrue(count(0.25) > count(1.0) && count(1.0) > count(2.0))
    }
}
