package com.takipli.oynat.core

import kotlin.math.abs

/**
 * Lightweight appearance evidence used to veto unsafe geometric ID switches.
 * Six independent 8-bin colour histograms: upper/lower clothing, R/G/B.
 * This is deliberately not advertised as a trained neural Re-ID model.
 */
const val APPEARANCE_BINS = 48
const val MIN_APPEARANCE_SIMILARITY = 0.87

fun appearanceSimilarity(a: List<Double>?, b: List<Double>?): Double? {
    if (a == null || b == null || a.size != APPEARANCE_BINS || b.size != APPEARANCE_BINS) return null
    if (a.any { !it.isFinite() || it < 0.0 } || b.any { !it.isFinite() || it < 0.0 }) return null
    // Each channel in each half sums to one, so the largest possible L1 distance is 12.
    return (1.0 - a.indices.sumOf { abs(a[it] - b[it]) } / 12.0).coerceIn(0.0, 1.0)
}

/** Accumulates stable, unoccluded crop descriptors without retaining image pixels. */
class AppearanceGallery {
    private class Entry(val mean: DoubleArray, var count: Int, var lastT: Double)
    private val gallery = HashMap<Int, Entry>()

    fun restore(saved: Map<String, List<Double>>?) {
        saved.orEmpty().forEach { (key, value) ->
            val id = key.toIntOrNull() ?: return@forEach
            if (id >= 0 && appearanceSimilarity(value, value) != null)
                gallery[id] = Entry(value.toDoubleArray(), 1, Double.NEGATIVE_INFINITY)
        }
    }

    fun observe(id: Int, t: Double, descriptor: List<Double>): Boolean {
        if (id < 0 || !t.isFinite() || appearanceSimilarity(descriptor, descriptor) == null) return false
        val e = gallery[id]
        if (e == null) {
            gallery[id] = Entry(descriptor.toDoubleArray(), 1, t)
            return true
        }
        if (t < e.lastT || t - e.lastT < 0.5) return false
        // Never contaminate a person's reference with a suddenly different crop.
        if ((appearanceSimilarity(e.mean.toList(), descriptor) ?: 0.0) < 0.72) return false
        val alpha = 1.0 / (e.count.coerceAtMost(9) + 1)
        for (i in e.mean.indices) e.mean[i] += alpha * (descriptor[i] - e.mean[i])
        e.count++; e.lastT = t
        return true
    }

    fun snapshot(): Map<String, List<Double>> = gallery.mapKeys { it.key.toString() }.mapValues { it.value.mean.toList() }
}
