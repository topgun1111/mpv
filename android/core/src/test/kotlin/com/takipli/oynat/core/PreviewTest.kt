package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Part 12: overlay of one sample (skeleton rows, part box, camera crop). Same synthetic person as PickTest. */
class PreviewTest {
    private val cfg = Config()
    private val row: List<Double> = run {
        val pts = mapOf(0 to (0.30 to 0.15), 15 to (0.27 to 0.85), 16 to (0.33 to 0.85))
        (0 until N_KPT).flatMap { j -> pts[j]?.let { listOf(it.first, it.second, 0.9) } ?: listOf(0.0, 0.0, 0.0) }
    }
    private val s = Sample(0.0, d = listOf(listOf(1.0, 0.2, 0.1, 0.4, 0.9, 0.9), listOf(2.0, 0.6, 0.2, 0.7, 0.6, 0.8)), kp = mapOf("1" to row))

    @Test
    fun noTargetShowsOnlyPersons() {
        val o = previewOverlay(s, 1000, 1000, null, cfg)
        assertEquals(listOf(1, 2), o.persons.map { it.id })
        assertTrue(o.persons.none { it.isTarget })
        assertNull(o.persons[1].kp) // person 2 has no pose
        assertEquals(3 * N_KPT, o.persons[0].kp?.size)
        assertNull(o.partBox); assertNull(o.crop)
    }

    @Test
    fun footTargetGivesPartBoxAndCrop() {
        val o = previewOverlay(s, 1000, 1000, Target(1, preset = "left_foot"), cfg)
        assertEquals(listOf(true, false), o.persons.map { it.isTarget })
        val pb = assertNotNull(o.partBox)
        assertEquals(0.27, (pb[0] + pb[2]) / 2, 1e-9); assertEquals(0.85, (pb[1] + pb[3]) / 2, 1e-9)
        assertEquals(0.08, pb[2] - pb[0], 1e-9) // kp_box x person height = 0.1 x 0.8
        // box height 0.08 -> scale 0.30 / 0.08 = 3.75 -> crop is 1/3.75 of the frame, clamped at the bottom edge
        val c = assertNotNull(o.crop)
        assertEquals(1 / 3.75, c[2] - c[0], 1e-9); assertEquals(1 / 3.75, c[3] - c[1], 1e-9)
        assertEquals(0.27, (c[0] + c[2]) / 2, 1e-9)
        assertEquals(0.85, (c[1] + c[3]) / 2, 1e-9)
    }

    @Test
    fun cropIsClampedInsideFrame() {
        val c = cropForBox(doubleArrayOf(0.02, 0.02, 0.08, 0.08), 1000, 1000, cfg)
        assertTrue(c.all { it >= -1e-9 && it <= 1 + 1e-9 })
        assertEquals(0.0, c[0], 1e-9); assertEquals(0.0, c[1], 1e-9)
    }

    @Test
    fun targetAbsentInSampleGivesNoBox() {
        val o = previewOverlay(s, 1000, 1000, Target(7, preset = "head"), cfg)
        assertNull(o.partBox); assertNull(o.crop)
    }

    @Test
    fun liveTargetResolvesFromSamplesSoFar() {
        assertNull(livePickTarget(emptyList(), 1000, 1000, TargetPick(0.0, 0.27, 0.85), cfg))
        assertEquals(Target(1, preset = "left_foot"), livePickTarget(listOf(s), 1000, 1000, TargetPick(0.0, 0.27, 0.85), cfg))
        assertNull(livePickTarget(listOf(s), 1000, 1000, TargetPick(0.0, 0.9, 0.9), cfg))
    }

    @Test
    fun infoLinesZoomStateAndCamera() {
        val none = previewOverlay(s, 1000, 1000, null, cfg)
        assertEquals(TargetState.NONE, none.targetState); assertNull(none.zoom)
        assertEquals("zoom -  NO TARGET" to "cam: no estimate", previewInfoLines(none))

        val foot = previewOverlay(s.copy(cam = listOf(1.0, 0.0, 0.03, 0.04)), 1000, 1000, Target(1, preset = "left_foot"), cfg)
        assertEquals(TargetState.TRACKING, foot.targetState)
        assertEquals(3.75, assertNotNull(foot.zoom), 1e-9) // same case as footTargetGivesPartBoxAndCrop
        assertEquals("zoom 3.8x  TRACKING" to "cam: moved 5.0%", previewInfoLines(foot))

        val lost = previewOverlay(s.copy(cut = 1), 1000, 1000, Target(7, preset = "head"), cfg)
        assertEquals(TargetState.LOST, lost.targetState)
        assertEquals("zoom -  LOST" to "CUT", previewInfoLines(lost))
    }

    @Test
    fun holdKeepsTheLastBoxesForAWhileThenLetsGo() {
        val hold = PreviewHold(1.5)
        val seen = hold.apply(1.0, previewOverlay(s, 1000, 1000, Target(1, preset = "left_foot"), cfg))
        assertEquals(TargetState.TRACKING, seen.targetState)
        val gone = s.copy(d = emptyList(), kp = null)
        val held = hold.apply(2.0, previewOverlay(gone, 1000, 1000, Target(1, preset = "left_foot"), cfg))
        assertEquals(TargetState.LOST, held.targetState)
        assertEquals(seen.crop!!.toList(), held.crop!!.toList())
        assertEquals("zoom 3.8x  LOST (holding)", previewInfoLines(held).first)
        assertNull(hold.apply(3.0, previewOverlay(gone, 1000, 1000, Target(1, preset = "left_foot"), cfg)).crop) // older than 1.5 s
        // a cut forgets everything
        hold.apply(4.0, previewOverlay(s, 1000, 1000, Target(1, preset = "left_foot"), cfg))
        assertNull(hold.apply(4.1, previewOverlay(gone.copy(cut = 1), 1000, 1000, Target(1, preset = "left_foot"), cfg)).crop)
    }
}
