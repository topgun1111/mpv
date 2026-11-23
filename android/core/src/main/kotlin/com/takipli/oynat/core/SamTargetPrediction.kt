package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.math.hypot

/**
 * Short-lived target velocity relative to camera motion, used only to compare
 * with an actual SAM mask. No predicted point becomes an output or memory mask.
 * Broken camera estimates, occlusions and reacquisitions reset velocity.
 */
class SamTargetPrediction {
    private var frame: Int? = null
    private var x = 0.0
    private var y = 0.0
    private var vx = 0.0
    private var vy = 0.0
    private var missed = 0
    private var valid = false
    private var stepValid = false
    private var baseX = 0.0
    private var baseY = 0.0

    fun seed(frameIndex: Int, cx: Double, cy: Double) {
        require(frameIndex >= 0)
        require(cx.isFinite() && cy.isFinite() && cx in 0.0..1.0 && cy in 0.0..1.0)
        frame = frameIndex
        x = cx; y = cy
        vx = 0.0; vy = 0.0
        missed = 0; valid = true; stepValid = false
    }

    /** Adjacent frame in either direction; null falls back to the legacy distance. */
    fun advance(nextFrame: Int, camera: SamCameraMotion?): DoubleArray? {
        val from = frame ?: return null
        frame = nextFrame
        stepValid = false
        if (abs(nextFrame.toLong() - from.toLong()) != 1L || !valid) {
            vx = 0.0; vy = 0.0; valid = false
            return null
        }
        val base = camera?.project(x, y, from, nextFrame)
        if (base == null) {
            vx = 0.0; vy = 0.0; valid = false
            return null
        }
        baseX = base[0]; baseY = base[1]
        // After three frames without accepted masks, retain camera flow only.
        val inertia = when (missed) {
            0 -> 0.80
            1 -> 0.50
            2 -> 0.25
            else -> 0.0
        }
        val nx = baseX + vx * inertia
        val ny = baseY + vy * inertia
        if (!nx.isFinite() || !ny.isFinite() || nx !in -0.15..1.15 || ny !in -0.15..1.15) {
            vx = 0.0; vy = 0.0; valid = false
            return null
        }
        x = nx.coerceIn(0.0, 1.0); y = ny.coerceIn(0.0, 1.0)
        missed++
        stepValid = true
        return doubleArrayOf(x, y)
    }

    /** Only call after SAM and TrackGate accept the observed mask. */
    fun observe(cx: Double, cy: Double, cleanAndContinuous: Boolean) {
        if (!cx.isFinite() || !cy.isFinite() || cx !in 0.0..1.0 || cy !in 0.0..1.0) return
        if (cleanAndContinuous && stepValid && missed == 1) {
            // Remove camera displacement; learn only motion of the target.
            val rx = cx - baseX
            val ry = cy - baseY
            if (hypot(rx, ry) <= 0.16) {
                // Reverse direction promptly instead of extrapolating stale momentum.
                val gain = if (vx * rx + vy * ry < 0.0) 0.90 else 0.65
                var dx = (1.0 - gain) * vx + gain * rx
                var dy = (1.0 - gain) * vy + gain * ry
                val speed = hypot(dx, dy)
                if (speed > 0.08) {
                    dx *= 0.08 / speed
                    dy *= 0.08 / speed
                }
                vx = dx; vy = dy
            } else {
                vx = 0.0; vy = 0.0
            }
        } else {
            vx = 0.0; vy = 0.0
        }
        x = cx; y = cy
        missed = 0; valid = true; stepValid = false
    }
}
