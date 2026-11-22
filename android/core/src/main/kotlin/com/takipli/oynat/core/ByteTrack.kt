package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.ln
import kotlin.math.max

/**
 * Port of `tracker/bytetrack.py::ByteTracker`: Kalman (cx, cy, a, h) + two-stage IoU matching.
 * `motion` (3x3 row-major, previous -> current frame) is the camera-compensation hook (Part 8 feeds it).
 */
class ByteTracker(
    private val highThr: Double = 0.5,
    private val lowThr: Double = 0.1,
    newThr: Double? = null,
    private val matchIou: Double = 0.3,
    private val secondIou: Double = 0.5,
    @Suppress("unused") private val unconfirmedIou: Double = 0.3,
    private val maxLost: Int = 30,
    private val minHits: Int = 1,
    /** Android only: tolerate camera-induced non-overlap, but reject ambiguous identity changes. */
    private val robustMotion: Boolean = false,
) {
    private val newThr: Double = newThr ?: highThr

    private class Internal(val id: Int, bbox: BBox, var score: Double) {
        var kf = KalmanBox(bbox)
        var age = 1
        var lost = 0
        var hits = 1
        var observed = bbox
        var appearance: List<Double>? = null
        val bbox: BBox get() = kf.bbox
        fun toTrack(robust: Boolean) = Track(id, if (robust && lost == 0) observed else bbox, score, age, lost)
    }

    private var tracks = mutableListOf<Internal>()
    private var nextId = 1

    /** When resuming a scan: new IDs must not collide with earlier samples. */
    fun setNextId(n: Int) {
        nextId = maxOf(nextId, n)
    }

    fun reset() {
        tracks = mutableListOf()
        nextId = 1
    }

    /** Drop all tracks but keep the ID counter (shot cut: old IDs are never reissued). */
    fun clear() {
        tracks = mutableListOf()
    }

    /** Last boxes of live tracks (camera estimation masks them when picking corners). */
    val boxes: List<BBox> get() = tracks.map { it.bbox }

    /** Tracks currently lost (waiting at their predicted position). */
    val lostTracks: List<Track> get() = tracks.filter { it.lost > 0 }.map { it.toTrack(robustMotion) }

    /** Returns the tracks SEEN in this frame. */
    fun update(detections: List<Detection>, motion: DoubleArray? = null, appearances: List<List<Double>?>? = null): List<Track> {
        require(appearances == null || appearances.size == detections.size) { "appearance count must match detections" }
        val highIndices = detections.indices.filter { detections[it].score >= highThr }
        val lowIndices = detections.indices.filter { detections[it].score >= lowThr && detections[it].score < highThr }
        val high = highIndices.map { detections[it] }
        val low = lowIndices.map { detections[it] }

        for (t in tracks) {
            t.kf.predict()
            if (motion != null) t.kf.compensate(motion)
            t.age += 1
            t.lost += 1 // reset on match
        }

        val seen = HashSet<Int>()
        fun applyMatches(pool: List<Internal>, dets: List<Detection>, indices: List<Int>, pairs: List<Pair<Int, Int>>) {
            for ((i, j) in pairs) {
                val t = pool[i]
                val incoming = dets[j].bbox
                // A Kalman filter lagging a large pan/zoom would otherwise keep reporting the old
                // box, causing the SAME visible pose to be dropped by the downstream IoU association.
                if (robustMotion && iouMatrix(listOf(t.bbox), listOf(incoming))[0][0] < 0.12) {
                    t.kf = KalmanBox(incoming)
                } else t.kf.update(incoming)
                t.observed = incoming
                t.score = dets[j].score
                t.lost = 0
                t.hits += 1
                if (robustMotion && dets[j].score >= 0.65 && appearances != null) {
                    val descriptor = appearances[indices[j]]
                    if (appearanceSimilarity(descriptor, descriptor) != null &&
                        (t.appearance == null || (appearanceSimilarity(t.appearance, descriptor) ?: 0.0) >= 0.86)) {
                        val prior = t.appearance
                        t.appearance = if (prior == null) descriptor else prior.indices.map { k -> 0.85 * prior[k] + 0.15 * descriptor!![k] }
                    }
                }
                seen.add(t.id)
            }
        }

        // Stage 1: high-score detections
        val pool = tracks.toList()
        val m1 = if (robustMotion) matchMotion(pool, high, highIndices, appearances, false, motion != null)
            else match(pool.map { it.bbox }, high.map { it.bbox }, matchIou)
        applyMatches(pool, high, highIndices, m1.pairs)
        val rest = m1.unmatchedTracks.map { pool[it] }

        // Stage 2: low-score detections vs remaining tracks (the heart of ByteTrack)
        val m2 = if (robustMotion) matchMotion(rest, low, lowIndices, appearances, true, motion != null)
            else match(rest.map { it.bbox }, low.map { it.bbox }, secondIou)
        applyMatches(rest, low, lowIndices, m2.pairs)

        // New objects: unmatched high-score detections
        for (j in m1.unmatchedDets) {
            val d = high[j]
            if (d.score >= newThr) {
                val t = Internal(nextId, d.bbox, d.score)
                if (robustMotion && d.score >= 0.65) t.appearance = appearances?.get(highIndices[j])
                nextId += 1
                tracks.add(t)
                seen.add(t.id)
            }
        }

        tracks = tracks.filter { it.lost <= maxLost }.toMutableList()
        return tracks.filter { it.id in seen && it.hits >= minHits }.map { it.toTrack(robustMotion) }
    }

    /** Joint box-motion and appearance assignment. A doubtful match becomes a missing frame, never a forced ID switch. */
    private fun matchMotion(
        pool: List<Internal>, dets: List<Detection>, indices: List<Int>, appearances: List<List<Double>?>?, lowScore: Boolean,
        motionKnown: Boolean,
    ): MatchResult {
        if (pool.isEmpty() || dets.isEmpty()) return MatchResult(emptyList(), pool.indices.toList(), dets.indices.toList())
        val overlaps = iouMatrix(pool.map { it.bbox }, dets.map { it.bbox })
        val impossible = 1e6
        val multiple = pool.size > 1 || dets.size > 1
        val cost = Array(pool.size) { i -> DoubleArray(dets.size) { j ->
            val tr = pool[i]; val d = dets[j].bbox
            // With intermittent optical flow, Kalman velocity is often *less* reliable than
            // the last actually seen box (especially for a handheld camera reversing direction).
            val predicted = tr.bbox
            val last = tr.observed
            val useLast = !motionKnown && tr.lost <= 2 &&
                hypot(last.cx - d.cx, last.cy - d.cy) < hypot(predicted.cx - d.cx, predicted.cy - d.cy)
            val b = if (useLast) last else predicted
            val heightRatio = d.h / max(1.0, b.h)
            val widthRatio = d.w / max(1.0, b.w)
            val distance = hypot(b.cx - d.cx, b.cy - d.cy) / max(1.0, max(b.h, d.h))
            val overlap = overlaps[i][j]
            val app = appearanceSimilarity(tr.appearance, appearances?.get(indices[j]))
            val maxDistance = when {
                lowScore -> if (multiple) 0.42 else if (tr.lost <= 1) 1.80 else 1.15
                app != null && app >= 0.87 -> if (multiple) 1.00 else if (tr.lost <= 1) 1.80 else 1.50
                multiple -> 0.62
                else -> if (tr.lost <= 1) 1.80 else 1.10
            }
            if (!distance.isFinite() || !heightRatio.isFinite() || !widthRatio.isFinite() ||
                heightRatio !in 0.38..2.65 || widthRatio !in 0.32..3.1 ||
                (overlap < if (lowScore) secondIou else matchIou) && distance > maxDistance ||
                (app != null && app < 0.76 && !lowScore)) impossible
            else {
                val sizePenalty = abs(ln(heightRatio)) + 0.35 * abs(ln(widthRatio))
                val colorBonus = if (app != null && app >= 0.87) 0.24 * (app - 0.87) / 0.13 else 0.0
                0.58 * (1.0 - overlap) + 0.42 * distance + 0.18 * sizePenalty - colorBonus
            }
        } }
        val matched = linearAssignment(cost).filter { (i, j) ->
            if (cost[i][j] >= impossible) return@filter false
            if (!multiple) return@filter true
            // Requiring a clear nearest candidate protects a seated person's legs when another
            // person passes close by or two boxes cross during camera movement.
            val nextTrack = pool.indices.filter { it != i }.minOfOrNull { cost[it][j] } ?: impossible
            val nextDet = dets.indices.filter { it != j }.minOfOrNull { cost[i][it] } ?: impossible
            val margin = if (overlaps[i][j] >= 0.65) 0.06 else 0.14
            nextTrack - cost[i][j] >= margin && nextDet - cost[i][j] >= margin
        }
        val mt = matched.map { it.first }.toSet(); val md = matched.map { it.second }.toSet()
        return MatchResult(matched, pool.indices.filter { it !in mt }, dets.indices.filter { it !in md })
    }

    companion object {
        /** Same wiring as the PC app: `ByteTracker(low_thr=cfg.live_det_conf)`. */
        fun fromConfig(cfg: Config) = ByteTracker(lowThr = cfg.liveDetConf)

        /**
         * Android scan: the loss window is TIME based ([TRACK_LOST_S], at least the PC default of 30 samples), so a blocker that
         * covers the subject for a few seconds does not give it a new ID at higher scan fps (30 samples = only 1.5 s at 20 fps).
         */
        fun fromConfig(cfg: Config, fps: Double): ByteTracker =
            ByteTracker(lowThr = cfg.liveDetConf, maxLost = if (fps > 0.0) maxOf(30, Math.ceil(TRACK_LOST_S * fps).toInt()) else 30, robustMotion = true)

        const val TRACK_LOST_S = 6.0
    }
}
