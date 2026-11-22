package com.takipli.oynat.core

import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

// ---- Occlusion hardening of the pose path (Android app; the PC pipeline and its golden files are untouched: only `robust = true` uses this). ----
//
// 1. [relinkIds]: ByteTrack gives a person a NEW ID after a long block. Link the target to the ID that appears where it vanished.
// 2. [suspectSamples]: a blocker can take over the target's ID. Samples where the ID teleports (far more than a person can move, or a
//    sudden size change) are ignored, unless the ID stays at the new place for [SUSPECT_ACCEPT_RUN] samples in a row.

/** A new ID may continue the target if it first shows up within this many seconds after the target vanished. */
const val RELINK_WINDOW_S = 8.0
const val RELINK_MAX_CHAIN = 20
const val SUSPECT_ACCEPT_RUN = 8

private class Obs(val i: Int, val b: DoubleArray, val score: Double) // b = x1, y1, x2, y2 (normalized)

private fun observations(doc: TrackDoc): Map<Int, List<Obs>> {
    val m = HashMap<Int, MutableList<Obs>>()
    for ((i, s) in doc.samples.withIndex()) for (d in s.d) {
        if (d.size < 6) continue
        m.getOrPut(d[0].toInt()) { ArrayList() }.add(Obs(i, doubleArrayOf(d[1], d[2], d[3], d[4]), d[5]))
    }
    return m
}

/**
 * `ids` plus the IDs that continue them after an occlusion. Chain: take the last place any of the IDs was seen; the best new ID
 * (first seen after that, within [windowS], no cut in between) whose first box is close enough (allowance grows with the time
 * lost) and of a plausible size joins the group; repeat. IDs that already existed while the target was visible are never linked.
 */
fun relinkIds(doc: TrackDoc, ids: Set<Int>, windowS: Double = RELINK_WINDOW_S): Set<Int> {
    if (ids.isEmpty() || doc.samples.isEmpty()) return ids
    val obs = observations(doc)
    val (w, h) = videoSize(doc)
    val cuts = cutIndices(doc)
    val ts = doc.samples.map { it.t }
    val group = LinkedHashSet(ids)
    for (step in 0 until RELINK_MAX_CHAIN) {
        var last: Obs? = null
        var lastId: Int? = null
        for (id in group) obs[id]?.lastOrNull()?.let { o ->
            if (last == null || o.i > last!!.i || (o.i == last!!.i && o.score > last!!.score)) { last = o; lastId = id }
        }
        val l = last ?: return group
        val lh = (l.b[3] - l.b[1]) * h
        if (lh <= 1.0) return group
        val lcx = (l.b[0] + l.b[2]) / 2 * w; val lcy = (l.b[1] + l.b[3]) / 2 * h
        var best: Int? = null; var bestScore = Double.MAX_VALUE; var runnerUp = Double.MAX_VALUE
        for ((id, list) in obs) {
            if (id in group) continue
            val o = list.first()
            if (o.i <= l.i) continue
            val gap = ts[o.i] - ts[l.i]
            if (gap > windowS) continue
            if (cuts.any { it in (l.i + 1)..o.i }) continue
            val oh = (o.b[3] - o.b[1]) * h
            val ratio = oh / lh
            if (ratio < 0.5 || ratio > 2.0) continue
            val d = hypot((o.b[0] + o.b[2]) / 2 * w - lcx, (o.b[1] + o.b[3]) / 2 * h - lcy) / lh
            if (d > min(1.0 + 0.5 * gap, 3.5)) continue
            val colour = appearanceSimilarity(doc.appearance?.get(lastId.toString()), doc.appearance?.get(id.toString()))
            val neural = reidSimilarity(doc.reid?.get(lastId.toString()), doc.reid?.get(id.toString()))
            if (neural != null && neural < MIN_REID_SIMILARITY) continue
            if (colour != null && colour < MIN_APPEARANCE_SIMILARITY &&
                (neural == null || neural < STRONG_REID_SIMILARITY)) continue
            val penalty = neural?.let { (1.0 - it) * 1.4 } ?: (colour?.let { 1.0 - it } ?: 0.0)
            val score = d + 0.1 * gap + penalty
            if (score < bestScore) { runnerUp = bestScore; bestScore = score; best = id }
            else if (score < runnerUp) runnerUp = score
        }
        // Two nearly identical candidates: keep the old identity unlinked rather than
        // silently jumping to the wrong person. The user can still re-pick manually.
        if (runnerUp - bestScore < 0.10) return group
        group.add(best ?: return group)
    }
    return group
}

/**
 * Offline scans know the whole video, including frames BEFORE the user's pick.
 * Extend the selected ID towards earlier track fragments, then re-run the forward
 * relinker. A backward link without appearance evidence must be extremely near
 * in space and time; uncertain links are left unresolved, never guessed.
 */
fun relinkIdsBidirectional(doc: TrackDoc, ids: Set<Int>, windowS: Double = RELINK_WINDOW_S): Set<Int> {
    val group = LinkedHashSet(relinkIds(doc, ids, windowS))
    if (group.isEmpty() || doc.samples.isEmpty()) return group
    val obs = observations(doc)
    val (w, h) = videoSize(doc)
    val ts = doc.samples.map { it.t }
    val cuts = cutIndices(doc)
    for (step in 0 until RELINK_MAX_CHAIN) {
        var first: Obs? = null; var firstId: Int? = null
        for (id in group) obs[id]?.firstOrNull()?.let { o ->
            if (first == null || o.i < first!!.i || (o.i == first!!.i && o.score > first!!.score)) {
                first = o; firstId = id
            }
        }
        val f = first ?: break
        val fh = (f.b[3] - f.b[1]) * h
        if (fh <= 1.0) break
        val fx = (f.b[0] + f.b[2]) / 2 * w; val fy = (f.b[1] + f.b[3]) / 2 * h
        var best: Int? = null; var bestScore = Double.MAX_VALUE; var runnerUp = Double.MAX_VALUE
        for ((id, list) in obs) {
            if (id in group) continue
            val o = list.last()
            if (o.i >= f.i) continue // never merge two people simultaneously visible
            val gap = ts[f.i] - ts[o.i]
            if (gap < 0.0 || gap > windowS || cuts.any { it in (o.i + 1)..f.i }) continue
            val oh = (o.b[3] - o.b[1]) * h
            val ratio = oh / fh
            if (ratio !in 0.5..2.0) continue
            val dist = hypot((o.b[0] + o.b[2]) / 2 * w - fx, (o.b[1] + o.b[3]) / 2 * h - fy) / fh
            if (dist > min(1.0 + 0.5 * gap, 3.5)) continue
            val colour = appearanceSimilarity(doc.appearance?.get(firstId.toString()), doc.appearance?.get(id.toString()))
            val neural = reidSimilarity(doc.reid?.get(firstId.toString()), doc.reid?.get(id.toString()))
            if (neural != null && neural < MIN_REID_SIMILARITY) continue
            if (colour != null && colour < MIN_APPEARANCE_SIMILARITY &&
                (neural == null || neural < STRONG_REID_SIMILARITY)) continue
            if (neural == null && colour == null && (gap > 2.0 || dist > 0.7)) continue
            val penalty = neural?.let { (1.0 - it) * 1.4 } ?: (colour?.let { 1.0 - it } ?: 0.0)
            val score = dist + 0.1 * gap + penalty
            if (score < bestScore) { runnerUp = bestScore; bestScore = score; best = id }
            else if (score < runnerUp) runnerUp = score
        }
        if (best == null || runnerUp - bestScore < 0.10) break
        group.add(best)
    }
    return relinkIds(doc, group, windowS)
}

/** The target with its re-linked IDs (`linked`); free targets are returned unchanged (their anchor is handled in `buildTargetViews`). */
fun relinkTarget(doc: TrackDoc, target: Target, windowS: Double = RELINK_WINDOW_S): Target {
    if (target.free != null) return target
    val base = setOf(target.id) + target.linked
    val all = relinkIds(doc, base, windowS)
    return if (all.size == base.size) target else target.copy(linked = target.linked + (all - base))
}

/**
 * Samples where the target (any of `ids`) is at an impossible place: it moved more than ~1.2 person heights since the last good
 * sample (+0.5 per missing sample, up to 8), or its height changed by more than x2.2. A cut starts over. If it stays at the new
 * place for [SUSPECT_ACCEPT_RUN] samples in a row, that is where the person really is: the last of the run is accepted.
 */
fun suspectSamples(doc: TrackDoc, ids: Set<Int>): Set<Int> {
    val (w, h) = videoSize(doc)
    val out = HashSet<Int>()
    var base: DoubleArray? = null; var baseI = -1; var pending = 0
    for ((i, s) in doc.samples.withIndex()) {
        if ((s.cut ?: 0) != 0) { base = null; pending = 0 }
        val d = s.d.filter { it.size >= 6 && it[0].toInt() in ids }.maxByOrNull { it[5] } ?: continue
        val cx = (d[1] + d[3]) / 2 * w; val cy = (d[2] + d[4]) / 2 * h; val hp = (d[4] - d[2]) * h
        if (hp <= 1.0) continue
        val b = base
        if (b == null) { base = doubleArrayOf(cx, cy, hp); baseI = i; pending = 0; continue }
        val missing = max(i - baseI - 1, 0)
        val ok = hypot(cx - b[0], cy - b[1]) <= b[2] * (1.2 + 0.5 * min(missing, 8)) && hp / b[2] in 0.45..2.2
        if (ok) { base = doubleArrayOf(cx, cy, hp); baseI = i; pending = 0 }
        else {
            out.add(i); pending++
            if (pending >= SUSPECT_ACCEPT_RUN) { out.remove(i); base = doubleArrayOf(cx, cy, hp); baseI = i; pending = 0 }
        }
    }
    return out
}

/** The doc without the target's rows (box + keypoints) in `bad` samples. */
internal fun dropSamples(doc: TrackDoc, ids: Set<Int>, bad: Set<Int>): TrackDoc =
    doc.copy(samples = doc.samples.mapIndexed { i, s ->
        if (i !in bad) s else s.copy(d = s.d.filter { it.isEmpty() || it[0].toInt() !in ids }, kp = s.kp?.filterKeys { it.toIntOrNull() !in ids })
    })
