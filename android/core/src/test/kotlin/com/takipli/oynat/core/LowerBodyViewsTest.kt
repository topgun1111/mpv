package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class LowerBodyViewsTest {
    @Test
    fun combinedLegRegionHoldsThroughBriefMissingPoseThenExpires() {
        val doc = TrackDoc(
            version = 2,
            video = VideoInfo("", 1000, 1000),
            samples = listOf(Sample(0.0), Sample(0.25), Sample(1.5)),
        )
        val boxes = lowerBodyBoxes(doc, setOf(1), mapOf(0 to doubleArrayOf(0.5, 0.65, 0.30, 0.42)), Config())
        assertTrue(0 in boxes)
        assertTrue(1 in boxes, "short occlusion should preserve anatomical framing")
        assertTrue(2 !in boxes, "long loss should be left to the normal lost/zoom-out handling")
        assertEquals(boxes.getValue(0)[2], boxes.getValue(1)[2], 1e-9)
    }
}
