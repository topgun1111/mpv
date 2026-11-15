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
        assertEquals("zoom -  LOST (ID not in frame)" to "CUT", previewInfoLines(lost))
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

    @Test
    fun liveRelinkFollowsTheNewIdAfterTheTrackerReissuesIt() {
        // person 1 walks off the tracker's radar at t=1; the same person comes back as ID 7 at the same place at t=1.2
        val a = Sample(0.0, d = listOf(listOf(1.0, 0.40, 0.2, 0.50, 0.8, 0.9)))
        val b = Sample(1.0, d = listOf(listOf(1.0, 0.41, 0.2, 0.51, 0.8, 0.9)))
        val c = Sample(1.2, d = listOf(listOf(7.0, 0.42, 0.2, 0.52, 0.8, 0.9)))
        val t = liveRelink(listOf(a, b, c), 1000, 1000, Target(1), c)
        assertEquals(listOf(7), t?.linked)
        assertEquals(TargetState.TRACKING, previewOverlay(c, 1000, 1000, t, cfg).targetState)
        // target present in the current sample, or no target, or a free target: unchanged
        val keep = Target(1)
        assertTrue(liveRelink(listOf(a, b), 1000, 1000, keep, b) === keep)
        assertNull(liveRelink(listOf(a), 1000, 1000, null, a))
    }

    @Test
    fun pointPickIsFramedInsideThePersonNotAsTheWholePerson() {
        // two dots on the lower legs of person 1 (box y 0.1..0.9): the preview frames the dots, so it zooms in; the person box alone stays at 1x
        val first = Sample(0.0, d = listOf(listOf(1.0, 0.40, 0.10, 0.60, 0.90, 0.9)))
        val pick = FreePick(0.0, 0.50, 0.75, id = 1, dots = listOf(listOf(0.46, 0.70), listOf(0.54, 0.80)))
        val target = Target(1, free = pick)
        val ref = freeRef(listOf(first), target)
        assertNotNull(ref)
        val now = Sample(0.5, d = listOf(listOf(1.0, 0.50, 0.10, 0.70, 0.90, 0.9))) // the person walked right by 0.1
        val o = previewOverlay(now, 1000, 1000, target, cfg, ref)
        assertEquals(TargetState.TRACKING, o.targetState)
        assertTrue((o.zoom ?: 0.0) > 1.2)
        assertEquals(0.6, (o.partBox!![0] + o.partBox!![2]) / 2, 0.02) // dots moved with the person
        assertNull(freeRef(listOf(first), Target(1))) // a person target has no free reference
    }
}
