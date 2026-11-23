package com.takipli.oynat.core

import kotlin.math.hypot
import kotlin.math.min

/**
 * Zero-lag, offline smoothing of SAM Rectangle *output centres*.
 *
 * Three real, adjacent SAM rows are compared with the time-interpolated centre
 * between their neighbours. Small deviations (segmentation jitter) are
 * attenuated; large deviations (rapid pans, reversals or camera-distance
 * changes) pass through unchanged. This is symmetric in time and therefore
 * never introduces the delay of a causal low-pass filter.
 *
 * No tracking gaps are invented or bridged. Identity, confidence and the
 * mask-derived width/height are never modified, so target retention and zoom
 * measurements remain under SAM's control. The picked sample is kept exact.
 */
object SamAdaptiveSmoothing {
    private const val MIN_CONF = 0.35
    private const val MAX_STEP_S = 0.35
    private const val MAX_BLEND = 0.80
    private const val MIN_JITTER = 0.004
    private const val MAX_JITTER = 0.025

    fun smooth(
        rows: List<List<Double>>,
        times: List<Double>,
        pickedIndex: Int = -1,
        aspect: Double = 1.0,
    ): List<List<Double>> {
        if (rows.size < 3 || times.size != rows.size ||
            !aspect.isFinite() || aspect <= 0.0) return rows
        val result = rows.toMutableList()
        fun good(row: List<Double>): Boolean =
            row.size >= 5 && row.take(5).all { it.isFinite() } &&
                row[0] in 0.0..1.0 && row[1] in 0.0..1.0 &&
                row[2] >= MIN_CONF && row[3] > 0.0 && row[4] > 0.0

        for (i in 1 until rows.lastIndex) {
            if (i == pickedIndex) continue
            val left = rows[i - 1]; val mid = rows[i]; val right = rows[i + 1]
            if (!good(left) || !good(mid) || !good(right)) continue
            val dt0 = times[i] - times[i - 1]
            val dt1 = times[i + 1] - times[i]
            if (!dt0.isFinite() || !dt1.isFinite() ||
                dt0 <= 0.0 || dt1 <= 0.0 || dt0 > MAX_STEP_S || dt1 > MAX_STEP_S) continue

            // Interpolate in real time: uneven scan timestamps are not equally spaced.
            val u = dt0 / (dt0 + dt1)
            val predictedX = left[0] + (right[0] - left[0]) * u
            val predictedY = left[1] + (right[1] - left[1]) * u
            // Normalized frame-height coordinates keep horizontal and vertical
            // movement comparable in portrait and landscape footage.
            val residual = hypot((mid[0] - predictedX) * aspect, mid[1] - predictedY)
            val targetH = min(mid[3] * aspect, mid[4])
            val threshold = (0.06 * targetH).coerceIn(MIN_JITTER, MAX_JITTER)
            // Preserve genuinely linear movement bit-for-bit (including floating-point roundoff).
            if (residual <= 1e-12 || residual >= threshold) continue

            // Gradually disable smoothing as a genuine corner/reversal emerges.
            val fraction = residual / threshold
            val blend = MAX_BLEND * (1.0 - fraction * fraction) * (1.0 - fraction * fraction)
            val filtered = mid.toMutableList()
            filtered[0] = (mid[0] + blend * (predictedX - mid[0])).coerceIn(0.0, 1.0)
            filtered[1] = (mid[1] + blend * (predictedY - mid[1])).coerceIn(0.0, 1.0)
            result[i] = filtered
        }
        return result
    }
}
