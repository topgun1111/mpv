package com.takipli.oynat.core

import kotlinx.serialization.Serializable
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sqrt

// ---- Part 16a: free-point target (any spot the user taps, not only a joint), multi-pass fusion, smooth sampling. ----

/** User pick: normalized frame point at time `t`; `id` = person it sits on (null = smallest box containing it); `zoom` = log2. */
@Serializable
data class FreePick(val t: Double, val x: Double, val y: Double, val id: Int? = null, val zoom: Double? = null,
    /** Part 18: freehand region(s): polygons of `[x, y]` normalized; x/y above = centre of their bounds. */
    val shapes: List<List<List<Double>>> = emptyList(),
    /** Region + `zoom` null: the area is kept at this fraction of the frame (size lock, zoom follows its size). Null = [regionFill] default. */
    val fill: Double? = null,
    /** Multi-dot pick (2..3 taps on one limb/object): normalized `[x, y]`; x/y above = their centroid. Framed like a region: the group's extent sets the zoom. */
    val dots: List<List<Double>> = emptyList(),
    /**
     * "Keep distance" (fixed-zoom picks): `zoom` is the zoom at the pick frame, and from there the zoom follows the object's apparent
     * size (it grows = it came closer = zoom out), so the object keeps the size it had when picked, like a cameraman who steps back.
     */
    val keepDist: Boolean = false,
) {
    /** Region or multi-dot pick: the target has an extent (zoom follows its size) instead of being a bare point. */
    val framed: Boolean get() = shapes.isNotEmpty() || dots.size >= 2
}

/**
 * Point observations from the phone, aligned to `TrackDoc.samples`; rows `[x, y, conf]` normalized, empty = lost.
 * `a` = primary pass (LK + template from the pick, both directions in time); `b` = verification/refine pass
 * (reverse run or higher fps on weak spans). Either may be empty.
 */
@Serializable
data class PointTrack(val a: List<List<Double>> = emptyList(), val b: List<List<Double>> = emptyList())

/**
 * Multi-dot pick: `tracks[d][i]` = `[x, y, conf]` of dot `d` at sample `i` (empty = lost), `start` = the dots at pick time.
 * Returns one `[x, y, conf, w, h]` row per sample (the region row format): the centre is the median of the dots' votes
 * (each dot minus its pick-time offset from the centroid, so one drifting dot is outvoted when there are 3), the size is the
 * dots' bounding box while all of them are tracked and the last full size while one is lost. Empty row = every dot lost.
 */
fun combineDots(tracks: List<List<List<Double>>>, start: List<List<Double>>, n: Int): List<List<Double>> {
    val m = start.size
    if (m < 2 || tracks.size != m) return List(n) { emptyList() }
    val cx0 = start.sumOf { it[0] } / m; val cy0 = start.sumOf { it[1] } / m
    val offX = start.map { it[0] - cx0 }; val offY = start.map { it[1] - cy0 }
    fun median(v: List<Double>): Double { val s = v.sorted(); return if (s.size % 2 == 1) s[s.size / 2] else (s[s.size / 2 - 1] + s[s.size / 2]) / 2.0 }
    var lastW = start.maxOf { it[0] } - start.minOf { it[0] }
    var lastH = start.maxOf { it[1] } - start.minOf { it[1] }
    return (0 until n).map { i ->
        val ok = (0 until m).filter { d -> tracks[d].getOrNull(i)?.let { it.size >= 3 && it[2] > 0.0 } == true }
        if (ok.isEmpty()) return@map emptyList<Double>()
        val cx = median(ok.map { tracks[it][i][0] - offX[it] }); val cy = median(ok.map { tracks[it][i][1] - offY[it] })
        if (ok.size == m) {
            lastW = ok.maxOf { tracks[it][i][0] } - ok.minOf { tracks[it][i][0] }
            lastH = ok.maxOf { tracks[it][i][1] } - ok.minOf { tracks[it][i][1] }
        }
        listOf(cx, cy, ok.sumOf { tracks[it][i][2] } / ok.size, lastW, lastH)
    }
}

/** Point stored relative to the person (nearest <= 2 confident joints, offsets in person-height units; box fraction as fallback). */
class Anchor(val id: Int, val joints: IntArray, val offX: DoubleArray, val offY: DoubleArray, val u: Double, val v: Double, val hPx0: Double = 0.0)

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
        (pick.x - row[1]) / max(row[3] - row[1], 1e-6), (pick.y - row[2]) / max(row[4] - row[2], 1e-6), hPx,
    )
}

/** Where the picked spot should be in sample `i` if it simply moved with the person. Weak by design (conf <= 0.8). */
fun anchorAt(doc: TrackDoc, a: Anchor, i: Int, cfg: Config, alt: Set<Int> = emptySet()): AnchorPos? {
    val s = doc.samples[i]
    // `alt` = IDs the same person got after an occlusion (Relink.kt): the anchor keeps working when the tracker re-created the person
    val pid = if (personRow(s, a.id) != null) a.id else alt.firstOrNull { personRow(s, it) != null } ?: return null
    val row = personRow(s, pid) ?: return null
    val (w, h) = videoSize(doc)
    val hPx = (row[4] - row[2]) * h
    if (hPx <= 1.0) return null
    var sx = 0.0; var sy = 0.0; var sw = 0.0
    for ((k, j) in a.joints.withIndex()) {
        val kp = s.keypoint(pid, j)?.takeIf { it.conf >= cfg.kpMinConf } ?: continue
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
fun fuseFreePoint(doc: TrackDoc, pick: FreePick, cfg: Config, alt: Set<Int> = emptySet()): Map<Int, DoubleArray> {
    val n = doc.samples.size
    val (w, h) = videoSize(doc)
    val anchor = makeAnchor(doc, pick, cfg)
    val base = shapeBounds(pick.shapes) ?: if (pick.dots.size >= 2) shapeBounds(listOf(pick.dots)) else null
    val i0 = if (n > 0) nearestIndex(doc, pick.t) else 0
    fun obs(l: List<List<Double>>?, i: Int) = l?.getOrNull(i)?.takeIf { it.size >= 3 && it[2] > 0.0 }
    val raw = HashMap<Int, DoubleArray>()
    for (i in 0 until n) {
        val an = anchor?.let { anchorAt(doc, it, i, cfg, alt) }
        fun ok(p: List<Double>?): Boolean =
            p != null && (an == null || hypot((p[0] - an.x) * w, (p[1] - an.y) * h) / an.hPx <= GATE_HEIGHTS)
        var a = obs(doc.pt?.a, i)?.takeIf { ok(it) }
        var b = obs(doc.pt?.b, i)?.takeIf { ok(it) }
        if (a != null && b != null && hypot(a[0] - b[0], (a[1] - b[1]) * h / w) > AB_TOL) {
            val keepA = if (an != null) hypot(a[0] - an.x, a[1] - an.y) <= hypot(b[0] - an.x, b[1] - an.y) else a[2] >= b[2]
            if (keepA) b = null else a = null
        }
        var sx = 0.0; var sy = 0.0; var sw = 0.0; var conf = 0.0
        var zw = 0.0; var zh = 0.0; var zs = 0.0 // region size, only from rows that carry it (`[x, y, conf, w, h]`)
        for (p in listOf(a, b)) if (p != null) {
            val wt = p[2] * p[2] + 1e-6; sx += p[0] * wt; sy += p[1] * wt; sw += wt; conf = max(conf, p[2])
            if (p.size >= 5) { zw += p[3] * wt; zh += p[4] * wt; zs += wt }
        }
        if (an != null) { val wt = 0.15 * an.conf; sx += an.x * wt; sy += an.y * wt; sw += wt; if (sw == wt) conf = an.conf }
        if (i == i0) { sx += pick.x * 4.0; sy += pick.y * 4.0; sw += 4.0; conf = 1.0 } // the user's tap is ground truth
        if (sw > 0) {
            if (base == null) raw[i] = doubleArrayOf(sx / sw, sy / sw, conf)
            else { // region: without tracker size, the pick-time size scaled with the person (anchor), else unchanged
                val sc = if (an != null && anchor != null && anchor.hPx0 > 0) an.hPx / anchor.hPx0 else 1.0
                raw[i] = doubleArrayOf(sx / sw, sy / sw, conf, if (zs > 0) zw / zs else base[2] * sc, if (zs > 0) zh / zs else base[3] * sc)
            }
        }
    }
    val idx = raw.keys.sorted()
    val out = HashMap<Int, DoubleArray>()
    for ((q, i) in idx.withIndex()) {
        val p = raw.getValue(i)
        if (q == 0 || q == idx.size - 1 || idx[q + 1] - idx[q - 1] != 2) { out[i] = p; continue }
        val l = raw.getValue(idx[q - 1]); val r = raw.getValue(idx[q + 1])
        val mx = listOf(l[0], p[0], r[0]).sorted()[1]; val my = listOf(l[1], p[1], r[1]).sorted()[1]
        out[i] = if (hypot(p[0] - mx, p[1] - my) > SPIKE) p.copyOf().also { it[0] = mx; it[1] = my; it[2] = p[2] * 0.5 } else p
    }
    return out
}

/** Square boxes `[cx, cy, s, s]` around the fused point so `computeView` yields exactly the chosen zoom (log2), clamped to the config. */
fun freePointBoxes(doc: TrackDoc, pick: FreePick, cfg: Config, alt: Set<Int> = emptySet()): Map<Int, DoubleArray> {
    // Part 18: frame the drawn region itself (size lock). With a chosen zoom (`pick.zoom`) the region is only followed: fixed zoom like a tapped spot.
    if (pick.framed && pick.zoom == null)
        return fuseFreePoint(doc, pick, cfg, alt).mapValues { (_, p) -> doubleArrayOf(p[0], p[1], max(p.getOrElse(3) { 0.1 } * 1.15, 0.02), max(p.getOrElse(4) { 0.1 } * 1.15, 0.02)) }
    val z = (pick.zoom ?: 1.5).coerceIn(cfg.minZoom, cfg.maxZoom)
    val s = cfg.targetFill / 2.0.pow(z)
    // keep distance: a box k times bigger than at the pick makes computeView zoom out by log2(k), so the object stays the same size on screen
    val sc = if (pick.keepDist) freePointScale(doc, pick, cfg, alt) else emptyMap()
    return fuseFreePoint(doc, pick, cfg, alt).mapValues { (i, p) -> val k = sc[i] ?: 1.0; doubleArrayOf(p[0], p[1], s * k, s * k) }
}

/**
 * Apparent size of the followed object in each sample relative to the pick frame: 1 = as big as when picked, 2 = twice as big
 * (it came closer). Size source: the tracker's own box (rows `[x, y, conf, w, h]`, the SAM mask box) when it has one, else the anchor
 * person's height. Median of 5 against spikes, held through lost spans (last known value), clamped to 0.2..5. Empty = no size known
 * (the zoom then simply stays fixed).
 */
fun freePointScale(doc: TrackDoc, pick: FreePick, cfg: Config, alt: Set<Int> = emptySet()): Map<Int, Double> {
    val n = doc.samples.size
    if (n == 0) return emptyMap()
    val anchor = makeAnchor(doc, pick, cfg)
    fun trk(i: Int): Double? {
        for (l in listOf(doc.pt?.a, doc.pt?.b)) {
            val r = l?.getOrNull(i)?.takeIf { it.size >= 5 && it[2] > 0.0 && it[3] > 1e-4 && it[4] > 1e-4 } ?: continue
            return sqrt(r[3] * r[4]) // geometric mean: independent of the frame's aspect ratio
        }
        return null
    }
    // reference = median tracker size within 0.5 s of the pick (the first mask is the one the user confirmed)
    val ref = (0 until n).filter { abs(doc.samples[it].t - pick.t) <= 0.5 }.mapNotNull { trk(it) }.sorted().let { if (it.isEmpty()) null else it[it.size / 2] }
    val raw = HashMap<Int, Double>()
    for (i in 0 until n) {
        val tr = if (ref != null) trk(i)?.let { it / ref } else null
        val an = if (tr == null && anchor != null && anchor.hPx0 > 0) anchorAt(doc, anchor, i, cfg, alt)?.let { it.hPx / anchor.hPx0 } else null
        (tr ?: an)?.let { raw[i] = it.coerceIn(0.2, 5.0) }
    }
    if (raw.isEmpty()) return emptyMap()
    val idx = raw.keys.sorted()
    val med = HashMap<Int, Double>()
    for ((q, i) in idx.withIndex()) {
        val w = (maxOf(0, q - 2)..minOf(idx.size - 1, q + 2)).map { raw.getValue(idx[it]) }.sorted()
        med[i] = w[w.size / 2]
    }
    val out = HashMap<Int, Double>()
    var last = med.getValue(idx.first())
    for (i in 0 until n) { last = med[i] ?: last; out[i] = last }
    return out
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

// ---- Part 18: freehand region ----

/** `[cx, cy, w, h]` (normalized) of all polygon points, or null when there are none. */
fun shapeBounds(shapes: List<List<List<Double>>>): DoubleArray? {
    val pts = shapes.flatten().filter { it.size >= 2 }
    if (pts.isEmpty()) return null
    val x1 = pts.minOf { it[0] }; val x2 = pts.maxOf { it[0] }; val y1 = pts.minOf { it[1] }; val y2 = pts.maxOf { it[1] }
    return doubleArrayOf((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)
}

/** Douglas-Peucker: drops points closer than `eps` (normalized) to the simplified line, keeps the ends. */
fun simplifyStroke(pts: List<List<Double>>, eps: Double): List<List<Double>> {
    if (pts.size < 3) return pts
    val keep = BooleanArray(pts.size); keep[0] = true; keep[pts.size - 1] = true
    val stack = ArrayDeque<Pair<Int, Int>>(); stack.add(0 to pts.size - 1)
    while (stack.isNotEmpty()) {
        val (a, b) = stack.removeLast()
        var far = -1; var fd = eps
        val dx = pts[b][0] - pts[a][0]; val dy = pts[b][1] - pts[a][1]; val len = hypot(dx, dy)
        for (i in a + 1 until b) {
            val d = if (len < 1e-12) hypot(pts[i][0] - pts[a][0], pts[i][1] - pts[a][1])
            else abs(dy * (pts[i][0] - pts[a][0]) - dx * (pts[i][1] - pts[a][1])) / len
            if (d > fd) { fd = d; far = i }
        }
        if (far >= 0) { keep[far] = true; stack.add(a to far); stack.add(far to b) }
    }
    return pts.filterIndexed { i, _ -> keep[i] }
}

/** Free pick for drawn region(s): position = centre of their bounds. */
fun regionPick(t: Double, shapes: List<List<List<Double>>>, id: Int? = null): FreePick {
    val b = shapeBounds(shapes) ?: return FreePick(t, 0.5, 0.5, id)
    return FreePick(t, b[0], b[1], id, shapes = shapes)
}

/**
 * Fill used when the target is a drawn region. `targetFill` (0.30) is meant for a small tapped spot or a person: with it a
 * drawn area taller than 30% of the frame never zoomed at all (zoom clamps to 1x) and smaller ones only grew to 30%.
 * A drawn area should fill the frame, so the default 0.30 maps to 0.90 (fits both width and height with a small margin);
 * the "fill" tuning slider still works, scaled the same way (0.10 -> 0.30 ... 0.85 -> 0.98).
 */
fun regionFill(targetFill: Double, base: Double = 0.90): Double = (targetFill / 0.30 * base).coerceIn(0.30, 0.98)
