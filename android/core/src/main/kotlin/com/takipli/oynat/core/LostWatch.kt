package com.takipli.oynat.core

/**
 * Raises ONE alert when the target has been absent for [alertS] seconds of video time (scan time), so the app can vibrate and let the user
 * pick again. Silent until the target has been seen at least once, and for [cooldownS] after each alert, [reset] or [snooze].
 */
class LostWatch(private val alertS: Double = 2.0, private val cooldownS: Double = 4.0) {
    private var seen = false
    private var absentSince = Double.NaN
    private var quietUntil = Double.NEGATIVE_INFINITY

    /** One call per scanned sample; `present` = the target is in this sample. True exactly when the alert fires. */
    fun update(t: Double, present: Boolean): Boolean {
        if (present) { seen = true; absentSince = Double.NaN; return false }
        if (!seen || t < quietUntil) return false
        if (absentSince.isNaN()) absentSince = t
        if (t - absentSince >= alertS) { absentSince = Double.NaN; quietUntil = t + cooldownS; return true }
        return false
    }

    /** The user picked a new target: forget the absence and wait until it has been seen again (and until video time [untilT]). */
    fun reset(untilT: Double) { absentSince = Double.NaN; quietUntil = untilT; seen = false }

    /** The user chose to go on without changing anything: stay quiet until video time [untilT], then alert again if it is still gone. */
    fun snooze(untilT: Double) { absentSince = Double.NaN; quietUntil = untilT }
}
