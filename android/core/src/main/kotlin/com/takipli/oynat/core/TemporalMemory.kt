package com.takipli.oynat.core

import kotlin.math.exp
import kotlin.math.hypot

/** Android robust view tracking: extrapolate a reliable target box across a bounded absence. */
const val DEFAULT_OCCLUSION_MEMORY_S = 3.0

/**
 * Keep the last reliable person/part size and a damped, camera-compensated velocity
 * for at most [holdS] seconds. Weak person-box slices do not teach the motion
 * model: while the memory is fresh, the predicted part box wins over that slice.
 * After expiry the original weak slice is available again. Never predict before
 * the first reliable observation or across a cut / malformed timestamp.
 *
 * This changes only robust Android views; PC/golden views remain untouched.
 */
fun temporalMemoryBoxes(
    doc: TrackDoc,
    boxes: Map<Int, DoubleArray>,
    holdS: Double = DEFAULT_OCCLUSION_MEMORY_S,
    weakIndices: Set<Int> = emptySet(),
): Map<Int, DoubleArray> {
    if (doc.samples.isEmpty() || !holdS.isFinite() || holdS <= 0.0) return boxes
    val (w, h) = videoSize(doc)
    val aspect = w.toDouble() / h
    val out = boxes.mapValuesTo(HashMap()) { (_, b) -> b.copyOf() }
    var px = 0.0; var py = 0.0
    var vx = 0.0; var vy = 0.0
    var bw = 0.0; var bh = 0.0
    var lastStrong = -1
    var strongT = 0.0; var stepT = 0.0

    fun reset() { lastStrong = -1; vx = 0.0; vy = 0.0 }
    fun camera(x: Double, y: Double, transform: List<Double>?): Pair<Double, Double> {
        if (transform == null || transform.size < 4) return x to y
        val a = transform[0]; val b = transform[1]; val tx = transform[2]; val ty = transform[3]
        val scale = hypot(a, b)
        if (!a.isFinite() || !b.isFinite() || !tx.isFinite() || !ty.isFinite() ||
            scale !in 0.7..1.4 || kotlin.math.abs(tx) > 1.0 || kotlin.math.abs(ty) > 1.0) return x to y
        return (a * x - b * y + tx) to (b * x + a * y + ty)
    }

    for ((i, sample) in doc.samples.withIndex()) {
        val t = sample.t
        if (!t.isFinite() || (sample.cut ?: 0) != 0 || (lastStrong >= 0 && t <= stepT)) reset()
        if (!t.isFinite()) continue
        val b = boxes[i]
        val reliable = i !in weakIndices && b != null && b.size >= 4 &&
            b.take(4).all { it.isFinite() } && b[2] > 0.0 && b[3] > 0.0

        if (reliable) {
            val candidate = b!!
            val x = candidate[0] * aspect; val y = candidate[1]
            if (lastStrong == i - 1 && t > stepT) {
                val (cx, cy) = camera(px, py, sample.cam)
                val dt = t - stepT
                var speedX = (x - cx) / dt; var speedY = (y - cy) / dt
                // Pose noise must not turn into a camera pan spanning the room.
                val maximum = 2.0 * bh // two target heights / second, in frame-height units
                val speed = hypot(speedX, speedY)
                if (speed > maximum && speed > 0.0) {
                    speedX *= maximum / speed; speedY *= maximum / speed
                }
                vx = 0.5 * vx + 0.5 * speedX
                vy = 0.5 * vy + 0.5 * speedY
            } else { vx = 0.0; vy = 0.0 }
            px = x; py = y; bw = candidate[2]; bh = candidate[3]
            lastStrong = i; strongT = t; stepT = t
            continue
        }

        if (lastStrong < 0) continue
        val dt = t - stepT
        val elapsed = t - strongT
        if (dt <= 0.0 || elapsed > holdS) { reset(); continue }
        // Predict in world coordinates first, then apply the camera's frame-to-frame motion.
        // The exponential damping makes this independent of scan FPS and bounds drift.
        val (originX, originY) = camera(px, py, sample.cam)
        val (x, y) = camera(px + vx * dt, py + vy * dt, sample.cam)
        px = x; py = y
        val damp = exp(-1.6 * dt)
        // Rotate/scale the velocity along with the camera, without adding its
        // translation to the target's own motion estimate.
        vx = (x - originX) / dt * damp
        vy = (y - originY) / dt * damp
        stepT = t
        out[i] = doubleArrayOf(px / aspect, py, bw, bh)
    }
    return out
}
