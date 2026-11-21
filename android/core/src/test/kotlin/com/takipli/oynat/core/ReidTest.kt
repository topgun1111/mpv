package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ReidTest {
    private fun identity(axis: Int) = List(REID_DIM) { if (it == axis) 1.0 else 0.0 }

    @Test fun cosineSimilarityRejectsMalformedInputs() {
        assertEquals(1.0, reidSimilarity(identity(0), identity(0)))
        assertEquals(0.0, reidSimilarity(identity(0), identity(1)))
        assertNull(reidSimilarity(null, identity(0)))
        assertNull(reidSimilarity(emptyList(), identity(0)))
        assertNull(reidSimilarity(List(REID_DIM) { 0.0 }, identity(0)))
        assertNull(reidSimilarity(List(REID_DIM) { Double.NaN }, identity(0)))
        assertNull(reidSimilarity(List(REID_DIM) { Double.POSITIVE_INFINITY }, identity(0)))
    }

    @Test fun galleryPreservesIdentityAndRejectedProbesAreThrottled() {
        val gallery = ReidGallery()
        assertTrue(gallery.observe(7, 0.0, identity(0)))
        assertFalse(gallery.observe(7, 0.1, identity(0)))
        assertFalse(gallery.observe(7, 1.0, identity(1))) // blocker must not poison identity
        assertFalse(gallery.due(7, 1.1)) // avoid repeated CPU inference on the blocker
        assertTrue(gallery.observe(7, 2.0, identity(0)))

        val restored = ReidGallery()
        restored.restore(gallery.snapshot() + ("bad" to identity(0)) + ("8" to listOf(0.0)))
        assertEquals(setOf("7"), restored.snapshot().keys)
        assertEquals(1.0, reidSimilarity(gallery.snapshot()["7"], restored.snapshot()["7"]))
        assertTrue(restored.due(7, 2.1)) // restored gallery can sample immediately
        assertFalse(gallery.observe(-1, 3.0, identity(0)))
        assertFalse(gallery.due(7, Double.NaN))
    }
}
