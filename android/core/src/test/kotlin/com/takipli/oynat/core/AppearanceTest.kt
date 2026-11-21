package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class AppearanceTest {
    private fun swatch(bin: Int) = List(APPEARANCE_BINS) { if (it % 8 == bin) 1.0 else 0.0 }

    @Test fun colourEvidenceIsBoundedAndRejectsInvalidVectors() {
        assertEquals(1.0, appearanceSimilarity(swatch(2), swatch(2)))
        assertEquals(0.0, appearanceSimilarity(swatch(2), swatch(6)))
        assertEquals(null, appearanceSimilarity(listOf(1.0), swatch(2)))
        assertEquals(null, appearanceSimilarity(List(APPEARANCE_BINS) { Double.NaN }, swatch(2)))
    }

    @Test fun galleryKeepsCleanHistoryAndPersistsThroughResumption() {
        val g = AppearanceGallery()
        assertTrue(g.observe(3, 0.0, swatch(2)))
        assertFalse(g.observe(3, 0.1, swatch(2))) // bounded sampling frequency
        assertFalse(g.observe(3, 1.0, swatch(6))) // a passing blocker must not poison the model
        assertTrue(g.observe(3, 1.1, swatch(2)))
        val recovered = AppearanceGallery()
        recovered.restore(g.snapshot())
        assertEquals(1.0, appearanceSimilarity(g.snapshot()["3"], recovered.snapshot()["3"]))
    }
}
