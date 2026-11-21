package com.takipli.oynat.core

import java.util.Locale
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.pow

// ---- Part 12: what the live scan preview draws for one sample. All coordinates normalized to the frame (0..1). ----

/** One tracked person: box `[x1, y1, x2, y2]`, keypoints `[x, y, conf] * 17` (null = no pose for this ID in this sample). */
class PersonOverlay(val id: Int, val box: DoubleArray, val kp: DoubleArray?, val isTarget: Boolean)

/** `partBox` = box of the chosen part, `crop` = the rectangle the follow camera would show (both `[x1, y1, x2, y2]`); null when there is no target in this sample. */
class PreviewOverlay(
    val persons: List<PersonOverlay>,
    val partBox: DoubleArray?,
    val crop: DoubleArray?,
    /** Zoom the follow camera would use (1.0 = whole frame); null when there is no crop. */
    val zoom: Double? = null,
    val targetState: TargetState = TargetState.NONE,
    /** This sample is a hard cut. */
    val cut: Boolean = false,
    /** Camera motion previous sample -> this sample, `[a, b, tx/h, ty/h]` (as `Sample.cam`); null = no estimate. */
    val cam: DoubleArray? = null,
)

/** NONE = no target picked / not found yet, TRACKING = the part is visible in this sample, LOST = target known but not in this sample. */
enum class TargetState { NONE, TRACKING, LOST }

/**
 * Keeps the last target box / crop on the live preview for [holdS] seconds while the target is missing (like the final views do:
 * `kp_hold_s`), marked LOST, so a short block does not make the green/red boxes flicker away. A cut or a time jump back resets it.
 */
class PreviewHold(private val holdS: Double) {
    private var part: DoubleArray? = null
    private var crop: DoubleArray? = null
    private var zoom: Double? = null
    private var lastT = Double.NEGATIVE_INFINITY

    fun apply(t: Double, o: PreviewOverlay): PreviewOverlay {
        if (o.cut || t < lastT) { part = null; crop = null; zoom = null; lastT = Double.NEGATIVE_INFINITY }
        if (o.partBox != null && o.crop != null) { part = o.partBox; crop = o.crop; zoom = o.zoom; lastT = t; return o }
        val c = crop
        if (o.targetState == TargetState.LOST && c != null && t - lastT <= holdS)
            return PreviewOverlay(o.persons, part, c, zoom, TargetState.LOST, o.cut, o.cam)
        return o
    }
}

/** Two short status lines drawn on the preview: zoom + target state, then camera motion / cut. Plain ASCII-safe, locale independent. */
fun previewInfoLines(o: PreviewOverlay): Pair<String, String> {
    val z = o.zoom?.let { String.format(Locale.US, "%.1fx", it) } ?: "-"
    val st = when (o.targetState) {
        TargetState.TRACKING -> "TRACKING"
        TargetState.LOST -> if (o.crop != null) "LOST (holding)" else "LOST (ID not in frame)"
        TargetState.NONE -> "NO TARGET"
    }
    val cam = when {
        o.cut -> "CUT"
        o.cam == null -> "cam: no estimate"
        else -> String.format(Locale.US, "cam: moved %.1f%%", hypot(o.cam[2], o.cam[3]) * 100) // translation in frame-height units
    }
    return "zoom $z  $st" to cam
}

/** Crop the camera would use for a `[cx, cy, w, h]` (normalized) box: `computeView` + the centre/size maths of `cropRect`, unrounded. */
fun cropForBox(box: DoubleArray, w: Int, h: Int, cfg: Config, minFit: Double = 0.0): DoubleArray {
    val bw = box[2] * w; val bh = box[3] * h
    val b = BBox(box[0] * w - bw / 2, box[1] * h - bh / 2, box[0] * w + bw / 2, box[1] * h + bh / 2)
    val v = computeView(b, w.toDouble(), h.toDouble(), cfg.targetFill, cfg.minZoom, cfg.maxZoom, minFit)
    val half = 0.5 / 2.0.pow(max(v.zoom, 0.0))
    val cx = 0.5 - v.panX; val cy = 0.5 - v.panY
    return doubleArrayOf(cx - half, cy - half, cx + half, cy + half)
}

/** Raw (unsmoothed) part box of `target` in this one sample, `[cx, cy, w, h]`, or null when the person/part is absent. */
private fun partBoxNow(s: Sample, w: Int, h: Int, target: Target, cfg: Config): DoubleArray? {
    val doc = TrackDoc(version = 2, video = VideoInfo(w = w, h = h), samples = listOf(s))
    val ids = setOf(target.id) + target.linked
    val boxes = when {
        target.preset != null -> presetBoxes(doc, ids, target.preset, cfg)
        target.part != null -> jointBoxes(doc, ids, target.part, cfg)
        else -> personBoxes(doc, ids)
    }
    return boxes[0]
}

/** Where a point / dots / region pick sat inside its anchor person at pick time; lets the live preview frame the pick itself, not the whole person. */
class FreeRef(val box: DoubleArray, val pts: List<DoubleArray>)

/** Reference for a free target (null for other targets, or when the anchor person is not in the pick sample). */
fun freeRef(samples: List<Sample>, target: Target?): FreeRef? {
    val f = target?.free ?: return null
    if (samples.isEmpty() || target.id < 0) return null
    var bi = 0
    for (i in samples.indices) if (abs(samples[i].t - f.t) < abs(samples[bi].t - f.t)) bi = i
    val row = samples[bi].d.filter { it.size >= 6 && it[0].toInt() == target.id }.maxByOrNull { it[5] } ?: return null
    val pts = when {
        f.shapes.isNotEmpty() -> f.shapes.flatten().map { doubleArrayOf(it[0], it[1]) }
        f.dots.size >= 2 -> f.dots.map { doubleArrayOf(it[0], it[1]) }
        else -> listOf(doubleArrayOf(f.x, f.y))
    }
    return FreeRef(doubleArrayOf(row[1], row[2], row[3], row[4]), pts)
}

/** Live approximation of a free target: the pick keeps its place inside the anchor person's current box (the real point track runs after the scan). `[cx, cy, w, h]`. */
private fun freeBoxNow(s: Sample, target: Target, ref: FreeRef, cfg: Config): DoubleArray? {
    val f = target.free ?: return null
    val ids = setOf(target.id) + target.linked
    val row = s.d.filter { it.size >= 6 && it[0].toInt() in ids }.maxByOrNull { it[5] } ?: return null
    val rw = ref.box[2] - ref.box[0]; val rh = ref.box[3] - ref.box[1]
    if (rw <= 1e-6 || rh <= 1e-6) return null
    val cw = row[3] - row[1]; val ch = row[4] - row[2]
    val xs = ref.pts.map { row[1] + (it[0] - ref.box[0]) / rw * cw }
    val ys = ref.pts.map { row[2] + (it[1] - ref.box[1]) / rh * ch }
    val cx = (xs.min() + xs.max()) / 2; val cy = (ys.min() + ys.max()) / 2
    if (f.framed && f.zoom == null) return doubleArrayOf(cx, cy, max((xs.max() - xs.min()) * 1.15, 0.02), max((ys.max() - ys.min()) * 1.15, 0.02))
    val z = (f.zoom ?: 1.5).coerceIn(cfg.minZoom, cfg.maxZoom)
    val sz = cfg.targetFill / 2.0.pow(z)
    return doubleArrayOf(cx, cy, sz, sz)
}

fun previewOverlay(s: Sample, w: Int, h: Int, target: Target?, cfg: Config, freeRef: FreeRef? = null): PreviewOverlay {
    val ids = target?.let { setOf(it.id) + it.linked }.orEmpty()
    val persons = s.d.map { d ->
        val id = d[0].toInt()
        PersonOverlay(id, doubleArrayOf(d[1], d[2], d[3], d[4]), s.kp?.get(id.toString())?.toDoubleArray(), id in ids)
    }
    val box = target?.let { if (it.free != null && freeRef != null) freeBoxNow(s, it, freeRef, cfg) else partBoxNow(s, w, h, it, cfg) }
    val fp = target?.free
    val viewCfg = if (fp != null && freeRef != null && fp.framed && fp.zoom == null) cfg.copy(targetFill = regionFill(cfg.targetFill, fp.fill ?: 0.90)) else cfg
    val part = box?.let { doubleArrayOf(it[0] - it[2] / 2, it[1] - it[3] / 2, it[0] + it[2] / 2, it[1] + it[3] / 2) }
    val fit = if (target?.preset != null && target.preset != "person") PART_FIT else 0.0 // same framing as `buildTargetViews`
    val crop = box?.let { cropForBox(it, w, h, viewCfg, fit) }
    val state = when {
        target == null -> TargetState.NONE
        box != null -> TargetState.TRACKING
        else -> TargetState.LOST
    }
    return PreviewOverlay(
        persons, part, crop,
        zoom = crop?.let { 1.0 / (it[2] - it[0]) }, // crop width = 1 / 2^zoom of the frame
        targetState = state, cut = s.cut == 1, cam = s.cam?.takeIf { it.size >= 4 }?.toDoubleArray(),
    )
}

/** Target for the preview while the scan runs: the pick resolved on the samples so far (null until a person is at the pick). */
fun livePickTarget(samples: List<Sample>, w: Int, h: Int, pick: TargetPick, cfg: Config): Target? =
    if (samples.isEmpty()) null else resolvePick(TrackDoc(version = 2, video = VideoInfo(w = w, h = h), samples = samples), pick, cfg)

/**
 * Live preview only: when none of the target's IDs is in this sample (the tracker gave the person a new ID), link the target to the
 * ID that continues it, with the same rule the final views use (`relinkIds`), so the preview does not show LOST for the rest of the
 * scan. Returns `target` itself when it is present, free-form, or nothing can be linked. Cheap: runs only while the target is absent.
 */
fun liveRelink(samples: List<Sample>, w: Int, h: Int, target: Target?, current: Sample, appearance: Map<String, List<Double>>? = null, reid: Map<String, List<Double>>? = null): Target? {
    if (target == null || target.free != null) return target
    val ids = setOf(target.id) + target.linked
    if (current.d.any { it.size >= 6 && it[0].toInt() in ids }) return target
    return relinkTarget(TrackDoc(version = 2, video = VideoInfo(w = w, h = h), samples = samples, appearance = appearance, reid = reid), target)
}
