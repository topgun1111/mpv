package com.takipli.oynat.core

import kotlin.math.hypot
import kotlin.math.max

/** Seated/standing estimate used by the lower-body camera model. */
enum class LowerBodyPosture { UNKNOWN, SEATED, STANDING, TRANSITION }

/** One frame's lower-body estimate. Boxes are normalized [cx, cy, width, height]. */
data class LowerBodyEstimate(
    val visible: DoubleArray?,
    val anatomical: DoubleArray?,
    val posture: LowerBodyPosture,
    val confidence: Double,
    val held: Boolean,
)

/**
 * Stateful temporal model for a combined legs+feet target.
 *
 * It deliberately does not run a neural network. It stabilizes the existing Pose/SAM evidence, keeps the last reliable
 * anatomical extent through short occlusions, limits implausible frame-to-frame scale changes, and classifies posture
 * from COCO hip/knee/ankle geometry when enough landmarks are present.
 *
 * Input boxes and keypoints are normalized to 0..1. Keypoints use COCO-17 triples (x,y,confidence).
 */
class LowerBodyModel(
    private val minJointConfidence: Double = 0.25,
    private val holdSeconds: Double = 1.0,
    private val smoothing: Double = 0.35,
    private val maxScaleChangePerSecond: Double = 0.65,
) {
    private var lastTime: Double? = null
    private var stable: DoubleArray? = null
    private var lastReliable: DoubleArray? = null
    private var lastReliableTime: Double? = null
    private var posture = LowerBodyPosture.UNKNOWN
    private var postureCandidate = LowerBodyPosture.UNKNOWN
    private var postureVotes = 0

    init {
        require(minJointConfidence in 0.0..1.0)
        require(holdSeconds >= 0.0)
        require(smoothing in 0.0..1.0)
        require(maxScaleChangePerSecond > 0.0)
    }

    fun reset() {
        lastTime = null
        stable = null
        lastReliable = null
        lastReliableTime = null
        posture = LowerBodyPosture.UNKNOWN
        postureCandidate = LowerBodyPosture.UNKNOWN
        postureVotes = 0
    }

    /**
     * @param timeSeconds monotonically increasing media time
     * @param visibleBox current union from SAM/Pose, normalized [cx,cy,w,h], or null on a lost frame
     * @param keypoints COCO-17 normalized triples; null if Pose is unavailable
     * @param evidenceConfidence confidence in the current region, normally 0..1
     */
    fun update(timeSeconds: Double, visibleBox: DoubleArray?, keypoints: List<Double>?, evidenceConfidence: Double = 1.0): LowerBodyEstimate {
        require(timeSeconds.isFinite())
        require(visibleBox == null || visibleBox.size >= 4)
        require(evidenceConfidence.isFinite())
        val dt = (lastTime?.let { timeSeconds - it } ?: 0.0).coerceAtLeast(0.0)
        lastTime = timeSeconds
        val detectedPosture = classifyPosture(keypoints)
        updatePosture(detectedPosture)

        val valid = visibleBox?.takeIf { validBox(it) && evidenceConfidence >= 0.20 }
        if (valid != null) {
            val prev = stable
            val next = if (prev == null) valid.copyOf(4) else blendAndLimit(prev, valid, dt)
            stable = next
            // Only high-quality, plausible observations may refresh the anatomical anchor.
            if (evidenceConfidence >= 0.55 && (prev == null || scaleRatio(prev, valid) <= 1.65)) {
                lastReliable = next.copyOf()
                lastReliableTime = timeSeconds
            }
            return LowerBodyEstimate(valid.copyOf(4), next.copyOf(), posture, evidenceConfidence.coerceIn(0.0, 1.0), false)
        }

        val anchor = lastReliable
        val age = lastReliableTime?.let { timeSeconds - it } ?: Double.POSITIVE_INFINITY
        if (anchor != null && age in 0.0..holdSeconds) {
            stable = anchor.copyOf()
            return LowerBodyEstimate(null, anchor.copyOf(), posture, (1.0 - age / max(holdSeconds, 1e-6)).coerceIn(0.0, 1.0), true)
        }
        return LowerBodyEstimate(null, null, posture, 0.0, false)
    }

    private fun validBox(b: DoubleArray): Boolean = b.take(4).all { it.isFinite() } && b[2] in 0.002..1.5 && b[3] in 0.002..1.5

    private fun scaleRatio(a: DoubleArray, b: DoubleArray): Double = max(max(b[2] / max(a[2], 1e-6), a[2] / max(b[2], 1e-6)), max(b[3] / max(a[3], 1e-6), a[3] / max(b[3], 1e-6)))

    private fun blendAndLimit(previous: DoubleArray, current: DoubleArray, dt: Double): DoubleArray {
        val alpha = if (dt <= 0.0) smoothing else (1.0 - (1.0 - smoothing).powSafe(dt * 30.0)).coerceIn(0.08, 0.85)
        val out = DoubleArray(4)
        for (i in 0..1) out[i] = previous[i] + alpha * (current[i] - previous[i])
        val maxLogStep = maxScaleChangePerSecond * if (dt <= 0.0) (1.0 / 30.0) else dt
        for (i in 2..3) {
            val desired = kotlin.math.ln(max(current[i], 1e-6) / max(previous[i], 1e-6))
            val limited = desired.coerceIn(-maxLogStep, maxLogStep)
            val limitedCurrent = previous[i] * kotlin.math.exp(limited)
            out[i] = previous[i] + alpha * (limitedCurrent - previous[i])
        }
        return out
    }

    private fun Double.powSafe(n: Double): Double = kotlin.math.exp(kotlin.math.ln(this.coerceAtLeast(1e-6)) * n)

    private fun classifyPosture(kp: List<Double>?): LowerBodyPosture {
        if (kp == null || kp.size < 51) return LowerBodyPosture.UNKNOWN
        fun point(j: Int): Pair<Double, Double>? {
            val x = kp[3 * j]; val y = kp[3 * j + 1]; val c = kp[3 * j + 2]
            return if (x.isFinite() && y.isFinite() && c >= minJointConfidence) x to y else null
        }
        fun angle(a: Pair<Double, Double>, b: Pair<Double, Double>, c: Pair<Double, Double>): Double {
            val v1x = a.first - b.first; val v1y = a.second - b.second
            val v2x = c.first - b.first; val v2y = c.second - b.second
            val dot = v1x * v2x + v1y * v2y
            val den = hypot(v1x, v1y) * hypot(v2x, v2y)
            if (den < 1e-8) return 180.0
            return Math.toDegrees(kotlin.math.acos((dot / den).coerceIn(-1.0, 1.0)))
        }
        val angles = listOf(Triple(11, 13, 15), Triple(12, 14, 16)).mapNotNull { (hip, knee, ankle) ->
            val h = point(hip) ?: return@mapNotNull null
            val k = point(knee) ?: return@mapNotNull null
            val a = point(ankle) ?: return@mapNotNull null
            angle(h, k, a)
        }
        if (angles.isEmpty()) return LowerBodyPosture.UNKNOWN
        val mean = angles.average()
        return when {
            mean < 125.0 -> LowerBodyPosture.SEATED
            mean > 150.0 -> LowerBodyPosture.STANDING
            else -> LowerBodyPosture.TRANSITION
        }
    }

    private fun updatePosture(candidate: LowerBodyPosture) {
        if (candidate == LowerBodyPosture.UNKNOWN) return
        if (candidate == posture) { postureCandidate = candidate; postureVotes = 0; return }
        if (candidate == postureCandidate) postureVotes++ else { postureCandidate = candidate; postureVotes = 1 }
        if (postureVotes >= 3) { posture = candidate; postureVotes = 0 }
    }
}
