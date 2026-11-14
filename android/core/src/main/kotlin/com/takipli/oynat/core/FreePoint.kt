package com.takipli.oynat.core

import kotlinx.serialization.Serializable
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

// ---- Part 16a: free-point target (any spot the user taps, not only a joint), multi-pass fusion, smooth sampling. ----

/** User pick: normalized frame point at time `t`; `id` = person it sits on (null = smallest box containing it); `zoom` = log2. */
@Serializable
data class FreePick(val t: Double, val x: Double, val y: Double, val id: Int? = null, val zoom: Double? = null,
    /** Manual corrections (Part 17): rows `[t, x, y]`, exact ground truth at their sample, sorted by time. */
    val pins: List<List<Double>> = emptyList(),
)

/**
 * Point observations from the phone, aligned to `TrackDoc.samples`; rows `[x, y, conf]` normalized, empty = lost.
 * `a` = primary pass (LK + template from the pick, both directions in time); `b` = verification/refine pass
 * (reverse run or higher fps on weak spans). Either may be empty.
 */
@Serializable
data class PointTrack(val a: List<List<Double>> = emptyList(), val b: List<List<Double>> = emptyList())

/** Point stored relative to the person (nearest <= 2 confident joints, offsets in person-height units; box fraction as fallback). */
class Anchor(val id: Int, val joints: IntArray, val offX: DoubleArray, val offY: DoubleArray, val u: Double, val v: Double)

class AnchorPos(val x: Double, val y: Double, val conf: Double, val hPx: Double)

private fun personRow(s: Sample, id: Int): List<Double>? = s.d.filter { it[0].toInt() == id }.maxByOrNull { it[5] }

private fun nearestIndex(doc: TrackDoc, t: Double): Int {
    var best = 0
    for (i in doc.samples.indices) if (kotlin.math.abs(doc.samples[i].t - t) < kotlin.math.abs(doc.samples[best].t - t)) best = i
    return best
}

fun makeAnchor(doc: TrackDoc, pick: FreePick, cfg: Config): Anchor? {
    if (doc.samples.isEmpty()) return null
    val (w, h) = videoSize(doc)
    val s = doc.samples[nearestIndex(doc, pick.t)]
    val id = pick.id ?: s.d.filter { pick.x in it[1]..it[3] && pick.y in it[2]..it[4] }
        .minByOrNull { (it[3] - it[1]) * (it[4] - it[2]) }?.get(0)?.toInt() ?: return null
    val row = personRow(s, id) ?: return null
    val hPx = (row[4] - row[2]) * h
    if (hPx <= 1.0) return null
    val near = (0 until N_KPT).mapNotNull { j ->
        s.keypoint(id, j)?.takeIf { it.conf >= cfg.kpMinConf }?.let { Triple(j, it, hypot((pick.x - it.x) * w, (pick.y - it.y) * h)) }
    }.sortedBy { it.third }.take(2)
    return Anchor(
        id, IntArray(near.size) { near[it].first },
        DoubleArray(near.size) { (pick.x - near[it].second.x) * w / hPx },
        DoubleArray(near.size) { (pick.y - near[it].second.y) * h / hPx },
        (pick.x - row[1]) / max(row[3] - row[1], 1e-6), (pick.y - row[2]) / max(row[4] - row[2], 1e-6),
    )
}

/** Where the picked spot should be in sample `i` if it simply moved with the person. Weak by design (conf <= 0.8). */
fun anchorAt(doc: TrackDoc, a: Anchor, i: Int, cfg: Config): AnchorPos? {
    val s = doc.samples[i]
    val row = personRow(s, a.id) ?: return null
    val (w, h) = videoSize(doc)
    val hPx = (row[4] - row[2]) * h
    if (hPx <= 1.0) return null
    var sx = 0.0; var sy = 0.0; var sw = 0.0
    for ((k, j) in a.joints.withIndex()) {
        val kp = s.keypoint(a.id, j)?.takeIf { it.conf >= cfg.kpMinConf } ?: continue
        sx += (kp.x + a.offX[k] * hPx / w) * kp.conf; sy += (kp.y + a.offY[k] * hPx / h) * kp.conf; sw += kp.conf
    }
    if (sw > 0) return AnchorPos(sx / sw, sy / sw, min(0.8, sw / a.joints.size * 0.8), hPx)
    return AnchorPos(row[1] + a.u * (row[3] - row[1]), row[2] + a.v * (row[4] - row[2]), row[5] * 0.5, hPx)
}

private const val GATE_HEIGHTS = 0.35 // LK point farther than this many person heights from the anchor = drift/jump
private const val AB_TOL = 0.05       // passes a and b farther apart than this (frame height) disagree
private const val SPIKE = 0.03        // median-of-3 replaces a value that deviates this much (frame units)

/**
 * Fuses pass a, pass b and the person anchor into one `[x, y, conf]` per sample (missing sample = lost).
 * LK points that contradict the anchor are rejected; a/b disagreement is arbitrated by the anchor (else higher conf);
 * the anchor alone fills samples where the tracker lost the point (blur, fast limb, close shot); spikes are median-filtered.
 */
fun fuseFreePoint(doc: TrackDoc, pick: FreePick, cfg: Config): Map<Int, DoubleArray> {
    val n = doc.samples.size
    val (w, h) = videoSize(doc)
    val anchor = makeAnchor(doc, pick, cfg)
    val i0 = if (n > 0) nearestIndex(doc, pick.t) else 0
    fun obs(l: List<List<Double>>?, i: Int) = l?.getOrNull(i)?.takeIf { it.size >= 3 && it[2] > 0.0 }
    val raw = HashMap<Int, DoubleArray>()
    val pinned = pick.pins.filter { it.size >= 3 }.associate { nearestIndex(doc, it[0]) to it }
    for (i in 0 until n) {
        val pin = pinned[i]
        if (pin != null) { raw[i] = doubleArrayOf(pin[1], pin[2], 1.0); continue }
        val an = anchor?.let { anchorAt(doc, it, i, cfg) }
        fun ok(p: List<Double>?): Boolean =
            p != null && (an == null || hypot((p[0] - an.x) * w, (p[1] - an.y) * h) / an.hPx <= GATE_HEIGHTS)
        var a = obs(doc.pt?.a, i)?.takeIf { ok(it) }
        var b = obs(doc.pt?.b, i)?.takeIf { ok(it) }
        if (a != null && b != null && hypot(a[0] - b[0], (a[1] - b[1]) * h / w) > AB_TOL) {
            val keepA = if (an != null) hypot(a[0] - an.x, a[1] - an.y) <= hypot(b[0] - an.x, b[1] - an.y) else a[2] >= b[2]
            if (keepA) b = null else a = null
        }
        var sx = 0.0; var sy = 0.0; var sw = 0.0; var conf = 0.0
        for (p in listOf(a, b)) if (p != null) { val wt = p[2] * p[2] + 1e-6; sx += p[0] * wt; sy += p[1] * wt; sw += wt; conf = max(conf, p[2]) }
        if (an != null) { val wt = 0.15 * an.conf; sx += an.x * wt; sy += an.y * wt; sw += wt; if (sw == wt) conf = an.conf }
        if (i == i0) { sx += pick.x * 4.0; sy += pick.y * 4.0; sw += 4.0; conf = 1.0 } // the user's tap is ground truth
        if (sw > 0) raw[i] = doubleArrayOf(sx / sw, sy / sw, conf)
    }
    val idx = raw.keys.sorted()
    val out = HashMap<Int, DoubleArray>()
    for ((q, i) in idx.withIndex()) {
        val p = raw.getValue(i)
        if (i in pinned || q == 0 || q == idx.size - 1 || idx[q + 1] - idx[q - 1] != 2) { out[i] = p; continue }
        val l = raw.getValue(idx[q - 1]); val r = raw.getValue(idx[q + 1])
        val mx = listOf(l[0], p[0], r[0]).sorted()[1]; val my = listOf(l[1], p[1], r[1]).sorted()[1]
        out[i] = if (hypot(p[0] - mx, p[1] - my) > SPIKE) doubleArrayOf(mx, my, p[2] * 0.5) else p
    }
    return out
}

/** Square boxes `[cx, cy, s, s]` around the fused point so `computeView` yields exactly the chosen zoom (log2), clamped to the config. */
fun freePointBoxes(doc: TrackDoc, pick: FreePick, cfg: Config): Map<Int, DoubleArray> {
    val z = (pick.zoom ?: 1.5).coerceIn(cfg.minZoom, cfg.maxZoom)
    val s = cfg.targetFill / 2.0.pow(z)
    return fuseFreePoint(doc, pick, cfg).mapValues { (_, p) -> doubleArrayOf(p[0], p[1], s, s) }
}

/** Part 16a: like `viewAt` but C1 cubic Hermite with monotone (Fritsch-Butland) tangents: no velocity jumps, no overshoot. */
fun viewAtSmooth(views: List<ViewKey>, t: Double): View {
    val n = views.size
    if (n < 3 || t <= views.first()[0] || t >= views.last()[0]) return viewAt(views, t)
    var lo = 0; var hi = n - 1
    while (hi - lo > 1) { val mid = (lo + hi) / 2; if (views[mid][0] <= t) lo = mid else hi = mid }
    val h = views[hi][0] - views[lo][0]
    if (h <= 0.0) return viewAt(views, t)
    val s = (t - views[lo][0]) / h
    val h00 = (1 + 2 * s) * (1 - s) * (1 - s); val h10 = s * (1 - s) * (1 - s); val h01 = s * s * (3 - 2 * s); val h11 = s * s * (s - 1)
    fun tangent(k: Int, c: Int): Double {
        if (k == 0) return (views[1][c] - views[0][c]) / (views[1][0] - views[0][0])
        if (k == n - 1) return (views[k][c] - views[k - 1][c]) / (views[k][0] - views[k - 1][0])
        val hl = views[k][0] - views[k - 1][0]; val hr = views[k + 1][0] - views[k][0]
        val dl = (views[k][c] - views[k - 1][c]) / hl; val dr = (views[k + 1][c] - views[k][c]) / hr
        if (dl * dr <= 0.0) return 0.0
        val w1 = 2 * hr + hl; val w2 = hr + 2 * hl
        return (w1 + w2) / (w1 / dl + w2 / dr)
    }
    fun ch(c: Int) = h00 * views[lo][c] + h10 * h * tangent(lo, c) + h01 * views[hi][c] + h11 * h * tangent(hi, c)
    return View(ch(1), ch(2), ch(3))
}

// ---- Part 17: manual corrections ("pins") ----

/** Adds a pin at time `t` (replacing one within `tolS`); coordinates clamped to the frame. */
fun FreePick.withPin(t: Double, x: Double, y: Double, tolS: Double): FreePick =
    copy(pins = (pins.filter { abs(it[0] - t) > tolS } + listOf(listOf(t, x.coerceIn(0.0, 1.0), y.coerceIn(0.0, 1.0)))).sortedBy { it[0] })

fun FreePick.withoutPin(t: Double, tolS: Double): FreePick = copy(pins = pins.filter { abs(it[0] - t) > tolS })

/** Fused confidence per sample (0 = lost, 1 = pinned) for the editor timeline. */
fun freePointConfidence(doc: TrackDoc, pick: FreePick, cfg: Config): DoubleArray {
    val f = fuseFreePoint(doc, pick, cfg)
    return DoubleArray(doc.samples.size) { f[it]?.get(2) ?: 0.0 }
}

/** Next sample after/before `from` (dir = +1/-1) whose confidence is below `thr`, or null. */
fun nextWeak(conf: DoubleArray, from: Int, dir: Int, thr: Double = 0.4): Int? {
    var i = from + dir
    while (i in conf.indices) { if (conf[i] < thr) return i; i += dir }
    return null
}
