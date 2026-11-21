package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class SamPassCounterTest {
    @Test fun forwardAndBackwardPassesNeverResetTheProgressBar() {
        val progress = SamPassCounter(123)
        val visited = (1..124).map { progress.next() }
        assertEquals(247, progress.total)
        assertEquals((124..247).toList(), visited)
        assertFailsWith<IllegalStateException> { progress.next() }
    }

    @Test fun invalidFrameCountsAreRejected() {
        assertFailsWith<IllegalArgumentException> { SamPassCounter(0) }
        assertFailsWith<IllegalArgumentException> { SamPassCounter(Int.MAX_VALUE) }
    }
}
