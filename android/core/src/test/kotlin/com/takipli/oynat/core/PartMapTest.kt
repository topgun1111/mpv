package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Part 20: first-frame part map + highlight. Frame 1000 x 1000; one standing person (x 200..400, y 100..900), optionally a second one 400 px to the right. */
class PartMapTest {
    private val cfg = Config()

    // joint -> pixel position; the eyes and ears (1-4) stay at confidence 0
    private val joints = mapOf(
        0 to (300.0 to 150.0), 5 to (260.0 to 300.0), 6 to (340.0 to 300.0), 7 to (230.0 to 420.0), 8 to (370.0 to 420.0),
        9 to (220.0 to 520.0), 10 to (380.0 to 520.0), 11 to (275.0 to 550.0), 12 to (325.0 to 550.0),
        13 to (270.0 to 700.0), 14 to (330.0 to 700.0), 15 to (265.0 to 850.0), 16 to (335.0 to 850.0),
    )

    private fun pose(dx: Double = 0.0, score: Double = 0.9): Pose {
        val k = DoubleArray(3 * N_KPT)
        for ((j, xy) in joints) { k[3 * j] = xy.first + dx; k[3 * j + 1] = xy.second; k[3 * j + 2] = 0.9 }
        return Pose(BBox(200.0 + dx, 100.0, 400.0 + dx, 900.0), score, k)
    }

    private val one = firstFrameDoc(listOf(pose()), 1000, 1000, 0.0)
    private val two = firstFrameDoc(listOf(pose(), pose(400.0)), 1000, 1000, 0.0)

    @Test
    fun docIsNormalizedWithIdsFromOne() {
        val s = two.samples.single()
        assertEquals(listOf(1.0, 2.0), s.d.map { it[0] })
        assertEquals(0.2, s.d[0][1], 1e-9); assertEquals(0.9, s.d[0][4], 1e-9)
        assertEquals(0.6, s.d[1][1], 1e-9)
        assertEquals(0.265, s.kp!!.getValue("1")[3 * 15], 1e-9)
        assertEquals(0.665, s.kp!!.getValue("2")[3 * 15], 1e-9)
        assertEquals(1000, two.video.w)
    }

    @Test
    fun everyPersonGetsAllPartsAndOnlyConfidentJoints() {
        val ps = pickPersons(two, cfg)
        assertEquals(2, ps.size)
        for (p in ps) {
            assertEquals(PART_GROUPS, p.parts.keys.toList())
            assertEquals(joints.keys.sorted(), p.joints.map { it.first }.sorted()) // eyes/ears have no confidence
        }
        val foot = ps[0].parts.getValue("left_foot")
        assertTrue(0.265 in foot[0]..foot[2] && 0.85 in foot[1]..foot[3])
        assertTrue(ps[0].parts.values.all { b -> b.all { it in 0.0..1.0 } && b[0] < b[2] && b[1] < b[3] })
    }

    @Test
    fun partHitSmallestBoxWinsAndMissIsNull() {
        val ps = pickPersons(two, cfg)
        assertEquals(1 to "left_foot", partHit(ps, 0.265, 0.85)) // inside the leg too, the foot is smaller
        assertEquals(1 to "head", partHit(ps, 0.30, 0.15))
        assertEquals(2 to "left_foot", partHit(ps, 0.665, 0.85))
        assertNull(partHit(ps, 0.395, 0.105)) // on the person's box, outside every part
        assertNull(partHit(ps, 0.95, 0.5))
    }

    @Test
    fun highlightIsWhatTheScanResolves() {
        val pick = TargetPick(0.0, 0.265, 0.85)
        val h = assertNotNull(highlightPick(one, pick, cfg))
        assertEquals(resolvePick(one, pick, cfg), h.target)
        assertEquals(Target(1, preset = "left_foot"), h.target)
        val region = assertNotNull(presetRegions(one, "left_foot", cfg)[1])
        val box = assertNotNull(h.box)
        for (i in 0..3) assertEquals(region[i], box[i], 1e-9)
    }

    @Test
    fun chosenPresetWinsOverTheTappedJoint() {
        val h = assertNotNull(highlightPick(one, TargetPick(0.0, 0.30, 0.15, preset = "legs"), cfg))
        assertEquals(Target(1, preset = "legs"), h.target)
        val box = assertNotNull(h.box)
        assertTrue(box[3] >= 0.85 && box[0] <= 0.265 && box[2] >= 0.335) // both ankles inside
    }

    @Test
    fun exactJointAndWholePersonAndNobody() {
        val exact = assertNotNull(highlightPick(one, TargetPick(0.0, 0.265, 0.85, exact = true), cfg))
        assertEquals(Target(1, part = 15), exact.target)
        val b = assertNotNull(exact.box)
        assertEquals(0.225, b[0], 1e-9); assertEquals(0.305, b[2], 1e-9)
        assertEquals(0.81, b[1], 1e-9); assertEquals(0.89, b[3], 1e-9)

        val whole = assertNotNull(highlightPick(one, TargetPick(0.0, 0.395, 0.105), cfg))
        assertEquals(Target(1), whole.target)
        val wb = assertNotNull(whole.box)
        assertEquals(listOf(0.2, 0.1, 0.4, 0.9), wb.toList().map { Math.round(it * 1e6) / 1e6 })

        assertNull(highlightPick(one, TargetPick(0.0, 0.9, 0.9), cfg))
    }

    @Test
    fun presetRegionsIgnoreUnknownPreset() {
        assertTrue(presetRegions(one, "elbow", cfg).isEmpty())
        assertEquals(setOf(1, 2), presetRegions(two, "torso", cfg).keys)
    }

    @Test
    fun labels() {
        assertEquals("left arm", partLabel(Target(1, preset = "left_arm")))
        assertEquals("left ankle", partLabel(Target(1, part = 15)))
        assertEquals("whole person", partLabel(Target(1)))
        assertTrue(PART_GROUPS.all { it in PRESETS && it in PART_RGB })
    }
}
