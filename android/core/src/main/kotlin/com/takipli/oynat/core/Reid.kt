package com.takipli.oynat.core

import kotlin.math.sqrt

/** OSNet embeddings are 512-dimensional and already L2-normalized. */
const val REID_DIM = 512

/** Conservative initial gates; these are heuristics, not calibrated probabilities. */
const val MIN_REID_SIMILARITY = 0.78
const val STRONG_REID_SIMILARITY = 0.92

fun reidSimilarity(a: List<Double>?, b: List<Double>?): Double? {
    if (a == null || b == null || a.size != REID_DIM || b.size != REID_DIM) return null
    var dot = 0.0; var na = 0.0; var nb = 0.0
    for (i in 0 until REID_DIM) {
        val x = a[i]; val y = b[i]
        if (!x.isFinite() || !y.isFinite()) return null
        dot += x * y; na += x * x; nb += y * y
    }
    if (na !in 0.25..2.25 || nb !in 0.25..2.25) return null
    return (dot / sqrt(na * nb)).coerceIn(-1.0, 1.0)
}

/** Only clear, temporally consistent observations are allowed into the ID bank. */
class ReidGallery {
    private class Entry(val mean: DoubleArray, var count: Int, var lastT: Double)
    private val entries = HashMap<Int, Entry>()

    fun restore(saved: Map<String, List<Double>>?) {
        saved.orEmpty().forEach { (key, value) ->
            val id = key.toIntOrNull() ?: return@forEach
            if (id >= 0 && reidSimilarity(value, value) != null)
                entries[id] = Entry(value.toDoubleArray(), 1, Double.NEGATIVE_INFINITY)
        }
    }

    fun due(id: Int, t: Double): Boolean = id >= 0 && t.isFinite() &&
        (entries[id]?.let { t >= it.lastT + 0.9 } ?: true)

    fun observe(id: Int, t: Double, vector: List<Double>): Boolean {
        if (id < 0 || !t.isFinite() || reidSimilarity(vector, vector) == null) return false
        val e = entries[id]
        if (e == null) {
            entries[id] = Entry(vector.toDoubleArray(), 1, t)
            return true
        }
        if (!due(id, t)) return false
        // Throttle rejected observations too: an occluder must not trigger a
        // costly OSNet inference on every subsequent video sample.
        e.lastT = t
        if ((reidSimilarity(e.mean.toList(), vector) ?: -1.0) < 0.82) return false
        val alpha = 1.0 / (e.count.coerceAtMost(7) + 1)
        var norm = 0.0
        for (i in e.mean.indices) {
            e.mean[i] += alpha * (vector[i] - e.mean[i])
            norm += e.mean[i] * e.mean[i]
        }
        val scale = sqrt(norm)
        if (scale > 0.0) for (i in e.mean.indices) e.mean[i] /= scale
        e.count++
        return true
    }

    fun snapshot(): Map<String, List<Double>> = entries.mapKeys { it.key.toString() }
        .mapValues { it.value.mean.toList() }
}
