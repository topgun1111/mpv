package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max

/** Whether a body-part target has enough actual keypoint evidence on this frame. */
fun bodyPartVisible(sample: Sample, target: Target, cfg: Config): Boolean {
    val joints = target.part?.let { intArrayOf(it) } ?: PRESETS[target.preset] ?: return false
    val check = when (target.preset) {
        "left_leg", "right_leg", "legs" -> joints.filter { it in 13..16 }
        "left_arm", "right_arm" -> joints.filter { it in 7..10 }
        else -> joints.toList()
    }
    val ids = setOf(target.id) + target.linked
    for (id in ids) for (joint in check) {
        val k = sample.keypoint(id, joint)
        if (k != null && k.conf >= cfg.kpMinConf) return true
    }
    return false
}

/** SAM is an expensive second pass: skip it when pose provides an uninterrupted part track. */
fun needsBodySam(doc: TrackDoc, target: Target, cfg: Config): Boolean =
    target.free == null && (target.part != null || (target.preset != null && target.preset != "person")) &&
        doc.samples.any { !bodyPartVisible(it, target, cfg) }

/** Convert the user-selected joint/region into a bounded box prompt for SAM 2. */
fun bodySamSeed(doc: TrackDoc, target: Target, pickT: Double, cfg: Config): FreePick? {
    if (doc.samples.isEmpty() || !needsBodySam(doc, target, cfg)) return null
    val ids = setOf(target.id) + target.linked
    val boxes = when {
        target.part != null -> jointBoxes(doc, ids, target.part, cfg)
        target.preset != null -> presetBoxes(doc, ids, target.preset, cfg)
        else -> return null
    }
    val index = boxes.keys.filter { abs(doc.samples[it].t - pickT) <= 0.8 }
        .minByOrNull { abs(doc.samples[it].t - pickT) } ?: return null
    val b = boxes[index] ?: return null
    if (b.size < 4 || b.any { !it.isFinite() } || b[2] <= 0.0 || b[3] <= 0.0) return null
    val cx = b[0].coerceIn(0.0, 1.0); val cy = b[1].coerceIn(0.0, 1.0)
    val hw = max(b[2] * 0.6, 0.02); val hh = max(b[3] * 0.6, 0.02)
    val x1 = (cx - hw).coerceIn(0.0, 1.0); val x2 = (cx + hw).coerceIn(0.0, 1.0)
    val y1 = (cy - hh).coerceIn(0.0, 1.0); val y2 = (cy + hh).coerceIn(0.0, 1.0)
    if (x2 - x1 < 0.01 || y2 - y1 < 0.01) return null
    val polygon = listOf(listOf(x1, y1), listOf(x2, y1), listOf(x2, y2), listOf(x1, y2))
    return FreePick(doc.samples[index].t, cx, cy, target.id, shapes = listOf(polygon))
}

/**
 * Prefer actual pose joints. A memory-verified SAM mask fills only weak/missing pose
 * observations, gated by the last reliable part's position and size. Works in both
 * temporal directions from the user's pick; never overwrites a confident pose row.
 */
fun fuseBodySam(doc: TrackDoc, target: Target, pose: Map<Int, DoubleArray>, cfg: Config, pickT: Double): Map<Int, DoubleArray> {
    val sam = doc.pt?.a ?: return pose
    if (sam.size != doc.samples.size || pose.isEmpty()) return pose
    val origin = pose.keys.minByOrNull { abs(doc.samples[it].t - pickT) } ?: return pose
    val out = HashMap(pose)
    fun run(indices: IntProgression) {
        var last = pose[origin]?.copyOf() ?: return
        var lastT = doc.samples[origin].t
        for (i in indices) {
            if (bodyPartVisible(doc.samples[i], target, cfg) && pose[i] != null) {
                last = pose.getValue(i).copyOf(); lastT = doc.samples[i].t
                continue
            }
            val a = sam[i]
            if (a.size < 5 || a.take(5).any { !it.isFinite() } || a[2] < 0.60 || a[3] <= 0.0 || a[4] <= 0.0) continue
            val dt = abs(doc.samples[i].t - lastT)
            val size = max(last[2], last[3]).coerceAtLeast(0.02)
            if (hypot(a[0] - last[0], a[1] - last[1]) > size * (2.0 + dt.coerceAtMost(6.0))) continue
            val wRatio = a[3] / last[2].coerceAtLeast(0.01)
            val hRatio = a[4] / last[3].coerceAtLeast(0.01)
            if (wRatio !in 0.35..2.5 || hRatio !in 0.35..2.5) continue
            // A partially covered limb should not cause a sudden zoom into a tiny mask.
            val width = if (wRatio < 0.65) last[2] else a[3]
            val height = if (hRatio < 0.65) last[3] else a[4]
            val accepted = doubleArrayOf(a[0], a[1], width, height)
            out[i] = accepted; last = accepted; lastT = doc.samples[i].t
        }
    }
    run(origin until doc.samples.size)
    run(origin downTo 0)
    return out
}
