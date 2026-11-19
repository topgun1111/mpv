package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Target-lost alert (vibrate + pause) and the picks the user makes again after it. */
class LostWatchTest {
    @Test
    fun alertsOnceAfterTheTargetHasBeenGoneForAlertSeconds() {
        val w = LostWatch(alertS = 2.0, cooldownS = 4.0)
        assertFalse(w.update(0.0, true))
        assertFalse(w.update(1.0, false)); assertFalse(w.update(2.9, false))
        assertTrue(w.update(3.0, false))              // gone since 1.0 -> 2.0 s later
        assertFalse(w.update(3.5, false))              // quiet during the cooldown
        assertFalse(w.update(6.9, false))                // quiet until 3.0 + 4.0 = 7.0
        assertFalse(w.update(7.0, false))              // the absence is counted from here
        assertTrue(w.update(9.0, false))               // still gone 2.0 s later: alert again
    }

    @Test
    fun silentUntilTheTargetWasSeenAndWhenItComesBack() {
        val w = LostWatch(alertS = 1.0)
        assertFalse(w.update(0.0, false)); assertFalse(w.update(5.0, false)) // never seen: nothing to lose
        assertFalse(w.update(5.1, true))
        assertFalse(w.update(5.5, false)); assertFalse(w.update(5.9, true))  // back before alertS: no alert
        assertFalse(w.update(6.0, false)); assertTrue(w.update(7.1, false))
    }

    @Test
    fun resetWaitsForTheNewTargetAndSnoozeOnlyDelays() {
        val w = LostWatch(alertS = 1.0, cooldownS = 0.0)
        w.update(0.0, true); w.update(1.0, false)
        assertTrue(w.update(2.1, false))
        w.reset(untilT = 3.0)
        assertFalse(w.update(5.0, false)); assertFalse(w.update(9.0, false)) // new target not seen yet: quiet
        assertFalse(w.update(9.5, true))
        w.update(10.0, false); assertTrue(w.update(11.1, false))
        w.snooze(untilT = 20.0)
        assertFalse(w.update(15.0, false)); assertFalse(w.update(19.0, false))
        w.update(20.0, false); assertTrue(w.update(21.1, false))
    }

    @Test
    fun repickJoinsTheNewIdToTheTarget() {
        // person 1 at the left until t=0.2; person 7 (the same child, new ID) at the right from t=0.5
        val d1 = listOf(1.0, 0.2, 0.1, 0.4, 0.9, 0.9)
        val d7 = listOf(7.0, 0.6, 0.1, 0.8, 0.9, 0.9)
        val doc = TrackDoc(
            version = 2, video = VideoInfo(w = 1000, h = 1000, fps = 10.0, duration = 0.7), sampleFps = 10.0,
            samples = listOf(Sample(0.0, d = listOf(d1)), Sample(0.1, d = listOf(d1)), Sample(0.2, d = listOf(d1)),
                Sample(0.5, d = listOf(d7)), Sample(0.6, d = listOf(d7)), Sample(0.7, d = listOf(d7))),
        )
        val cfg = Config()
        val first = TargetPick(0.0, 0.3, 0.5)
        val again = TargetPick(0.6, 0.7, 0.5)
        val one = applyPicks(doc, first, emptyList(), cfg)!!
        assertEquals(listOf(), one.target!!.linked)
        val two = applyPicks(doc, first, listOf(again), cfg)!!
        assertEquals(1, two.target!!.id)
        assertEquals(listOf(7), two.target!!.linked)
        assertEquals(two.target, applyPicks(doc, first, listOf(again, again), cfg)!!.target) // the same re-pick twice adds nothing
        assertTrue(applyPicks(doc, TargetPick(0.0, 0.95, 0.05), listOf(again), cfg) == null) // first pick found nobody
    }
}
