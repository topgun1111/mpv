package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Occlusion-robust part boxes (seated person behind a desk); same numbers as `tests/test_parts_robust.py`. */
class PartRobustTest {
    private fun seated(knee: Triple<Double, Double, Double> = Triple(0.45, 1.05, 0.5)): MutableList<Double> {
        val row = MutableList(51) { 0.0 }
        fun set(j: Int, x: Double, y: Double, c: Double) { row[3 * j] = x; row[3 * j + 1] = y; row[3 * j + 2] = c }
        set(5, 0.4, 0.25, 0.9); set(6, 0.6, 0.25, 0.9); set(11, 0.42, 0.55, 0.8); set(12, 0.58, 0.55, 0.8)
        set(13, knee.first, knee.second, knee.third); set(15, 0.45, 1.4, 0.5)
        return row
    }

    @Test
    fun inventedLegJointsAreDroppedAndLegsHangFromTheHips() {
        val row = seated()
        val clean = sanitizeRow(row, 1000, 1000, 0.35, 500.0)
        assertEquals(0.0, clean[3 * 13 + 2], 1e-12); assertEquals(0.0, clean[3 * 15 + 2], 1e-12)
        val b = assertNotNull(anchoredLegBox("left_leg", row, 1000, 1000, 0.35, 500.0))
        assertEquals(0.42, b[0], 1e-9); assertEquals(0.7, b[1], 1e-9); assertEquals(0.3, b[3], 1e-9)
    }

    @Test
    fun plausibleLowConfidenceKneeIsKeptAndStandingPersonIsUntouched() {
        val row = seated(Triple(0.45, 0.8, 0.25))
        assertEquals(0.35, sanitizeRow(row, 1000, 1000, 0.35, 500.0)[3 * 13 + 2], 1e-12)
        val st = MutableList(51) { 0.0 }
        listOf(5 to (0.4 to 0.25), 6 to (0.6 to 0.25), 11 to (0.42 to 0.55), 12 to (0.58 to 0.55), 13 to (0.42 to 0.72), 14 to (0.58 to 0.72), 15 to (0.42 to 0.9), 16 to (0.58 to 0.9))
            .forEach { (j, p) -> st[3 * j] = p.first; st[3 * j + 1] = p.second; st[3 * j + 2] = 0.9 }
        assertEquals(st, sanitizeRow(st, 1000, 1000, 0.35, 800.0))
        assertNull(anchoredLegBox("head", st, 1000, 1000, 0.35, 800.0))
        assertTrue(anchoredLegBox("feet", st, 1000, 1000, 0.35, 800.0)!![1] > 0.55)
    }
}
