package com.takipli.oynat.core

/**
 * Tracks the expected size of a SAM region between reliable masks. Camera zoom
 * is only a weak cue: bound every step and the total extrapolation so noisy
 * background flow cannot permanently change the output crop or teach the
 * identity memory an occluding object.
 *
 * Predictions are used for size/occlusion checks, never to create a tracked
 * sample without a SAM mask. A confirmed clean mask resets the prediction.
 */
class SamScaleMemory {
    private var cleanArea = 0.0
    private var cleanWidth = 0.0
    private var cleanHeight = 0.0
    private var extrapolation = 1.0
    private var valid = false

    fun seed(area: Double, width: Double, height: Double) {
        require(area.isFinite() && area > 0.0 && area <= 1.0)
        require(width.isFinite() && width > 0.0 && width <= 1.0)
        require(height.isFinite() && height > 0.0 && height <= 1.0)
        cleanArea = area; cleanWidth = width; cleanHeight = height
        extrapolation = 1.0; valid = true
    }

    /** One adjacent video frame; null breaks the scale chain until a clean SAM mask confirms the size. */
    fun advance(cameraScale: Double?) {
        if (!valid) return
        if (cameraScale == null || !cameraScale.isFinite() || cameraScale !in 0.75..1.35) {
            extrapolation = 1.0; valid = false
            return
        }
        // The background and the person can be at different depths. Apply only
        // 75% of a bounded camera zoom estimate rather than trusting it as an
        // exact measurement of the subject's apparent size.
        val factor = 1.0 + 0.75 * (cameraScale.coerceIn(0.90, 1.10) - 1.0)
        extrapolation = (extrapolation * factor).coerceIn(0.5, 2.0)
    }

    /** Observed mask area relative to where a clean target should be now. */
    fun areaRatio(observedArea: Double): Double =
        if (cleanArea > 0.0 && observedArea.isFinite() && observedArea >= 0.0)
            observedArea / (cleanArea * extrapolation * extrapolation)
        else 0.0

    val expectedWidth: Double get() = (cleanWidth * extrapolation).coerceAtMost(1.0)
    val expectedHeight: Double get() = (cleanHeight * extrapolation).coerceAtMost(1.0)

    /** Update only from a confidence- and appearance-verified clean SAM mask. */
    fun observeClean(area: Double, width: Double, height: Double) {
        if (!area.isFinite() || area <= 0.0 || area > 1.0 ||
            !width.isFinite() || width <= 0.0 || width > 1.0 ||
            !height.isFinite() || height <= 0.0 || height > 1.0) return
        cleanArea = 0.8 * cleanArea + 0.2 * area
        cleanWidth = width; cleanHeight = height
        extrapolation = 1.0; valid = true
    }
}
