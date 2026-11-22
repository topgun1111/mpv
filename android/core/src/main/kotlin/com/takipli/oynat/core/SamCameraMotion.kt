package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot

/**
 * Projects a SAM target between consecutive decoded frames using background-camera motion.
 * Each entry maps frame (i - 1) to frame i in ORIGINAL image pixels; entry zero is null.
 * A failed estimate must never invent a position: callers retain their existing tracker fallback.
 */
class SamCameraMotion(private val steps: List<DoubleArray?>, private val width: Int, private val height: Int) {
    init { require(width > 0 && height > 0) }

    private fun reliableStep(from: Int, to: Int): DoubleArray? {
        if (abs(to - from) != 1 || from !in steps.indices || to !in steps.indices) return null
        val m = steps[if (to > from) to else from] ?: return null
        if (m.size != 9 || m.any { !it.isFinite() }) return null
        // CameraMotion produces a 2-D similarity, never a projective warp. Reject
        // jumps, cuts and malformed estimates instead of steering toward a blocker.
        val a = m[0]; val b = m[1]; val c = m[3]; val d = m[4]
        val scale = hypot(a, c)
        if (scale !in 0.75..1.35 || abs(atan2(c, a)) > Math.PI / 3 ||
            abs(a - d) > 0.08 || abs(b + c) > 0.08 ||
            abs(m[6]) > 1e-9 || abs(m[7]) > 1e-9 || abs(m[8] - 1.0) > 1e-9
        ) return null
        return m
    }

    /** Uniform camera zoom from `from` to `to` (reverse traversal uses its reciprocal). */
    fun scale(from: Int, to: Int): Double? {
        val m = reliableStep(from, to) ?: return null
        val factor = hypot(m[0], m[3])
        return if (to > from) factor else 1.0 / factor
    }

    /** Normalized input/output; works in both forward and reverse SAM passes. */
    fun project(x: Double, y: Double, from: Int, to: Int): DoubleArray? {
        if (!x.isFinite() || !y.isFinite()) return null
        if (from == to) return doubleArrayOf(x, y)
        val m = reliableStep(from, to) ?: return null
        val a = m[0]; val b = m[1]; val c = m[3]; val d = m[4]
        val px = x * width; val py = y * height
        val q = if (to > from) {
            doubleArrayOf(a * px + b * py + m[2], c * px + d * py + m[5])
        } else {
            val det = a * d - b * c
            if (abs(det) < 1e-8) return null
            val dx = px - m[2]; val dy = py - m[5]
            doubleArrayOf((d * dx - b * dy) / det, (a * dy - c * dx) / det)
        }
        val nx = q[0] / width; val ny = q[1] / height
        return if (nx.isFinite() && ny.isFinite() && nx in -0.5..1.5 && ny in -0.5..1.5) doubleArrayOf(nx, ny) else null
    }

    /** Axis-aligned envelope of a rotating rectangle, used only to guide fallback SAM prompts. */
    fun projectBounds(x1: Double, y1: Double, x2: Double, y2: Double, from: Int, to: Int): DoubleArray? {
        val corners = listOf(x1 to y1, x1 to y2, x2 to y1, x2 to y2)
            .map { (x, y) -> project(x, y, from, to) ?: return null }
        return doubleArrayOf(corners.minOf { it[0] }, corners.minOf { it[1] }, corners.maxOf { it[0] }, corners.maxOf { it[1] })
    }
}
