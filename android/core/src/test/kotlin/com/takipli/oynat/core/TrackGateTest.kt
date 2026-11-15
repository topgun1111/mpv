package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class TrackGateTest {
    private fun learned(sim: Double = 0.8) = TrackGate().also { g -> repeat(TrackGate.MIN_LEARN) { g.learn(sim) } }

    @Test fun rememberOnlyCleanFrames() {
        assertTrue(TrackGate.remember(0.8, 1.0))
        assertFalse(TrackGate.remember(0.5, 1.0))   // unsure
        assertFalse(TrackGate.remember(0.9, 0.4))   // mostly covered
        assertFalse(TrackGate.remember(0.9, 2.0))   // merged with something else
    }

    @Test fun cosineBasics() {
        assertEquals(1.0, TrackGate.cosine(floatArrayOf(1f, 2f), floatArrayOf(2f, 4f)), 1e-9)
        assertEquals(0.0, TrackGate.cosine(floatArrayOf(1f, 0f), floatArrayOf(0f, 1f)), 1e-9)
        assertEquals(0.0, TrackGate.cosine(floatArrayOf(), floatArrayOf()), 1e-9)
        assertEquals(0.0, TrackGate.cosine(floatArrayOf(0f, 0f), floatArrayOf(1f, 1f)), 1e-9)
    }

    @Test fun jumpAllowanceGrowsWithLostFrames() {
        assertFalse(TrackGate.isJump(0.2, 0.3, 0))
        assertTrue(TrackGate.isJump(0.6, 0.3, 0))
        assertFalse(TrackGate.isJump(0.6, 0.3, 4))  // lost for a while: the subject may have moved
    }

    @Test fun everythingPassesBeforeEnoughCleanFrames() {
        val g = TrackGate()
        assertTrue(g.accept(5.0, 0.3, 3, 0.0))
        assertEquals(0, g.rejected)
    }

    @Test fun lookalikeAfterLossIsRejectedButTheSubjectIsAccepted() {
        val g = learned(0.8)
        assertFalse(g.accept(0.1, 0.3, 5, 0.2))     // resumes on something that does not look like it
        assertTrue(g.accept(0.1, 0.3, 5, 0.7))      // the subject is back
        assertEquals(1, g.rejected)
    }

    @Test fun farJumpWhileTrackingNeedsSimilarityButNormalMotionDoesNot() {
        val g = learned(0.8)
        assertFalse(g.accept(0.9, 0.3, 0, 0.5))     // jumped across the frame onto something else
        assertTrue(g.accept(0.9, 0.3, 0, 0.7))      // a real fast move that still looks the same
        assertTrue(g.accept(0.05, 0.3, 0, 0.1))     // normal motion is never gated
    }

    @Test fun partialMaskKeepsTheLastCleanSize() {
        assertEquals(0.3 to 0.5, TrackGate.size(0.4, 0.1, 0.2, 0.3, 0.5))
        assertEquals(0.1 to 0.2, TrackGate.size(0.9, 0.1, 0.2, 0.3, 0.5))
        assertEquals(0.1 to 0.2, TrackGate.size(0.4, 0.1, 0.2, 0.0, 0.0)) // no clean size known yet
    }

    @Test fun longLossRelaxesTheResumeRuleSoItNeverDeadlocks() {
        val g = learned(0.8)                        // resume needs 0.6 x 0.8 = 0.48
        assertFalse(g.accept(0.1, 0.3, 5, 0.40))
        assertFalse(g.accept(0.1, 0.3, 12, 0.40))   // relaxing only starts after RELAX_FROM lost frames
        assertTrue(g.accept(0.1, 0.3, 36, 0.40))    // lost ~6 s: 0.24 is enough (a different angle / light)
        assertFalse(g.accept(0.1, 0.3, 36, 0.10))   // something that looks nothing like it is still refused
        assertEquals(1.0, TrackGate.relax(0), 1e-9); assertEquals(0.5, TrackGate.relax(1000), 1e-9)
    }
}
