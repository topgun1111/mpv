package com.takipli.oynat.core

import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Occlusion handling of the EdgeTAM memory tracker (pure maths; `SamEngine` applies it, this file is unit-tested).
 *  1. [remember]: only clean, confident, normal-sized frames go into the memory bank (a half-hidden subject or the blocker must not become "the subject").
 *  2. [accept]: a mask that jumps far, or reappears after a loss, must look like the subject (cosine of the object pointers). The threshold is
 *     relative to what this very scan measured on clean frames, so it needs no fixed calibration; until enough clean frames were seen, everything passes.
 *  3. [size]: a partly covered subject has a small mask; the camera keeps the last clean size instead of zooming in on the visible part.
 */
class TrackGate {
    private var ref = 0.0
    private var learned = 0
    var accepted = 0; private set
    var rejected = 0; private set

    /** Similarity of a clean, undisturbed frame: running average = what "the same subject" looks like in this video. */
    fun learn(sim: Double) { ref = if (learned == 0) sim else 0.9 * ref + 0.1 * sim; learned++ }

    fun note() { accepted++ }

    fun accept(dist: Double, boxSize: Double, lost: Int, sim: Double): Boolean {
        val ok = learned < MIN_LEARN || sim >= needed(dist, boxSize, lost)
        if (!ok) rejected++
        return ok
    }

    private fun needed(dist: Double, boxSize: Double, lost: Int): Double =
        max(if (lost > 0) RESUME_K * ref else 0.0, if (isJump(dist, boxSize, lost)) JUMP_K * ref else 0.0)

    fun summary(): String = "gate: kept $accepted, rejected $rejected (similarity ref ${"%.2f".format(java.util.Locale.ROOT, ref)}, ${learned} clean frames)"

    companion object {
        const val REMEMBER_CONF = 0.6
        const val REMEMBER_MIN_RATIO = 0.6
        const val REMEMBER_MAX_RATIO = 1.6
        const val PARTIAL_RATIO = 0.6
        const val MIN_LEARN = 3
        const val JUMP_K = 0.75
        const val RESUME_K = 0.6
        /** Frames in a row that are tracked but never "clean" (the subject really changed size): adapt anyway, never deadlock. */
        const val FORCE_CLEAN_FRAMES = 12

        fun remember(conf: Double, ratio: Double): Boolean = conf >= REMEMBER_CONF && ratio in REMEMBER_MIN_RATIO..REMEMBER_MAX_RATIO

        fun cosine(a: FloatArray, b: FloatArray): Double {
            if (a.isEmpty() || a.size != b.size) return 0.0
            var d = 0.0; var na = 0.0; var nb = 0.0
            for (i in a.indices) { d += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i] }
            return if (na <= 0.0 || nb <= 0.0) 0.0 else d / (sqrt(na) * sqrt(nb))
        }

        /** Far from where the subject was, allowing for its size and for every frame it was lost (after ~8 lost frames almost anywhere is allowed). */
        fun isJump(dist: Double, boxSize: Double, lost: Int): Boolean = dist > max(boxSize, 0.05) * (1.5 + 0.75 * min(lost, 8))

        fun size(ratio: Double, w: Double, h: Double, stableW: Double, stableH: Double): Pair<Double, Double> =
            if (ratio < PARTIAL_RATIO && stableW > 0.0 && stableH > 0.0) stableW to stableH else w to h
    }
}
