package com.takipli.oynat.core

/** Local diagnostic counters for evaluating real occlusion clips. */
data class OcclusionStats(
    val absentRuns: Int,
    val longestAbsentS: Double,
    val linkedIds: Int,
    val weakJointFrames: Int,
    val samUsableFrames: Int,
) {
    fun summary(): String = "absent-runs=$absentRuns max-absence=${"%.2f".format(java.util.Locale.ROOT, longestAbsentS)}s linked-ids=$linkedIds weak-joint-frames=$weakJointFrames SAM-masks=$samUsableFrames"
}

fun occlusionStats(doc: TrackDoc, cfg: Config = Config()): OcclusionStats {
    val target = doc.target ?: return OcclusionStats(0, 0.0, 0, 0, 0)
    val ids = setOf(target.id) + target.linked + if (target.free == null) relinkIdsBidirectional(doc, setOf(target.id) + target.linked) else emptySet()
    var runs = 0; var start: Double? = null; var longest = 0.0
    var weak = 0; var sam = 0
    for ((i, sample) in doc.samples.withIndex()) {
        val present = sample.d.any { it.size >= 6 && it[0].toInt() in ids }
        if (!present) {
            if (start == null) { start = sample.t; runs++ }
        } else if (start != null) {
            longest = maxOf(longest, sample.t - start)
            start = null
        }
        if ((target.part != null || (target.preset != null && target.preset != "person")) && !bodyPartVisible(sample, target, cfg)) weak++
        if (doc.pt?.a?.getOrNull(i)?.let { it.size >= 5 && it[2] >= 0.60 } == true) sam++
    }
    if (start != null && doc.samples.isNotEmpty()) longest = maxOf(longest, doc.samples.last().t - start)
    return OcclusionStats(runs, longest, (ids - target.id).size, weak, sam)
}
