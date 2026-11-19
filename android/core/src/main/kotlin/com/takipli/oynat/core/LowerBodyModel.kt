package com.takipli.oynat.core

import kotlin.math.max
import kotlin.math.min

/** Camera geometry used by the lower-body estimator. Coordinates remain in source-image space. */
enum class LowerBodyCameraProfile(val nominalUpTiltDegrees: Double) {
    /** Frontal camera placed around knee height and tilted slightly upward. */
    FRONTAL_SLIGHT_UP(8.0),
}

/**
 * Separates the anatomical target from the pixels that are currently visible.
 * `anatomicalBox` is the complete estimated leg/foot region; `visibleBox` is its
 * intersection with the image area below an optional horizontal desk-occlusion edge.
 * Boxes are [cx, cy, width, height], normalized to 0..1.
 *
 * The desk edge is deliberately an input, not guessed from a person mask: this avoids
 * silently learning the desk as part of the body. A later image-based desk-edge detector
 * can supply it without changing the anatomical model.
 */
data class LowerBodyEstimate(
    val anatomicalBox: DoubleArray,
    val visibleBox: DoubleArray?,
    val confidence: Double,
    val inferred: Boolean,
    val cameraProfile: LowerBodyCameraProfile,
)

/**
 * Estimate a seated person's lower-body envelope from COCO-17 keypoints.
 * If knees/ankles are hidden by a desk, the envelope is anchored at the hips and scaled
 * from shoulder-to-hip torso length. This is intentionally conservative for the frontal,
 * slightly-upward camera profile: implausible distal landmarks are not allowed to pull the
 * target onto the desk or another object.
 *
 * `deskOcclusionY` is an optional normalized image y-coordinate (0..1) of a detected
 * horizontal occlusion boundary. Pixels below that line are treated as visible. Pass null
 * until a reliable boundary detector is available.
 */
fun estimateLowerBody(
    row: List<Double>?,
    width: Int,
    height: Int,
    personHeightPx: Double,
    minConfidence: Double = 0.35,
    preset: String = "legs",
    deskOcclusionY: Double? = null,
    cameraProfile: LowerBodyCameraProfile = LowerBodyCameraProfile.FRONTAL_SLIGHT_UP,
): LowerBodyEstimate? {
    if (width <= 0 || height <= 0 || row == null || row.size < 3 * N_KPT) return null
    if (preset !in setOf("legs", "left_leg", "right_leg", "feet", "left_foot", "right_foot")) return null

    val clean = sanitizeRow(row, width, height, minConfidence, personHeightPx)
    val anchored = anchoredLegBox(preset, row, width, height, minConfidence, personHeightPx) ?: return null

    // If reliable distal joints survived sanitation, use them as evidence that the limb is
    // visible. The anchored envelope remains the stable anatomical target for framing.
    val joints = when (preset) {
        "left_leg" -> listOf(13, 15)
        "right_leg" -> listOf(14, 16)
        "left_foot" -> listOf(15)
        "right_foot" -> listOf(16)
        "feet" -> listOf(15, 16)
        else -> listOf(13, 14, 15, 16)
    }
    val reliableDistal = joints.count { clean[3 * it + 2] >= minConfidence }
    val inferred = reliableDistal == 0
    val confidence = if (inferred) 0.35 else min(0.95, 0.45 + 0.15 * reliableDistal)

    val anatomical = anchored.copyOf()
    val boundary = deskOcclusionY?.coerceIn(0.0, 1.0)
    val visible = if (boundary == null) anatomical.copyOf() else {
        val x1 = max(0.0, anatomical[0] - anatomical[2] / 2.0)
        val x2 = min(1.0, anatomical[0] + anatomical[2] / 2.0)
        val y1 = max(boundary, anatomical[1] - anatomical[3] / 2.0)
        val y2 = min(1.0, anatomical[1] + anatomical[3] / 2.0)
        if (x2 <= x1 || y2 <= y1) null else doubleArrayOf((x1 + x2) / 2.0, (y1 + y2) / 2.0, x2 - x1, y2 - y1)
    }

    return LowerBodyEstimate(anatomical, visible, confidence, inferred, cameraProfile)
}

/** Stateful short-occlusion stabilizer for anatomical boxes. It never expands the target to a blocker. */
class LowerBodyTemporalFilter(
    private val smoothing: Double = 0.35,
    private val maxMissingFrames: Int = 12,
) {
    private var previous: DoubleArray? = null
    private var missing = 0

    init {
        require(smoothing in 0.0..1.0)
        require(maxMissingFrames >= 0)
    }

    fun update(estimate: LowerBodyEstimate?): DoubleArray? {
        if (estimate == null) {
            missing++
            return if (missing <= maxMissingFrames) previous?.copyOf() else null
        }
        val next = estimate.anatomicalBox
        val old = previous
        val result = if (old == null || missing > maxMissingFrames) next.copyOf() else {
            DoubleArray(4) { i -> old[i] + smoothing * (next[i] - old[i]) }
        }
        previous = result
        missing = 0
        return result.copyOf()
    }

    fun reset() {
        previous = null
        missing = 0
    }
}
