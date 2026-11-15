package com.takipli.oynat.core

import kotlin.math.abs
import kotlin.math.sqrt

/**
 * Debug Part 1: predictive diagnostics (pure Kotlin, no Android imports, unit-tested).
 * Idea: the user cannot re-download the APK for every test, so one run must say what is wrong AND what is about to go wrong:
 * wrong model shapes, benchmark outliers, throttling, memory/battery/storage running out, broken timelines.
 */

enum class Sev { INFO, WARN, PREDICT, ERROR }

/** One diagnosis. [code] is a stable short id (grep-able in pasted logs), [msg] says what and what to do. */
data class Finding(val sev: Sev, val code: String, val msg: String) {
    fun text(): String = "$sev $code: $msg"
}

fun fmt1(v: Double): String = if (v.isNaN() || v.isInfinite()) "?" else (Math.round(v * 10.0) / 10.0).toString()

// ---------------------------------------------------------------- benchmarks

/**
 * Sanity checks on a timing summary. Seen on the phone: NPU encoder "mean 1196.7 ms (p95 598.3)": a mean above p95 can only
 * happen when a few runs are huge (first-run graph compile, thermal stall), so the mean is useless and the median is the number to trust.
 */
fun benchFindings(label: String, s: BenchStats): List<Finding> {
    val out = ArrayList<Finding>()
    if (s.n < 5) { out.add(Finding(Sev.INFO, "BENCH_FEW", "$label: only ${s.n} runs, numbers are rough")); return out }
    if (s.meanMs > s.p95Ms * 1.05) out.add(Finding(Sev.WARN, "BENCH_OUTLIER", "$label: mean ${fmt1(s.meanMs)} ms is above p95 ${fmt1(s.p95Ms)} ms (max ${fmt1(s.maxMs)}): a few runs are huge (first-run compile or stall). Trust the median ${fmt1(s.medianMs)} ms; warm up more or drop the first run."))
    else if (s.medianMs > 0 && s.maxMs > 8 * s.medianMs) out.add(Finding(Sev.WARN, "BENCH_SPIKE", "$label: slowest run ${fmt1(s.maxMs)} ms is more than 8x the median ${fmt1(s.medianMs)} ms."))
    if (s.medianMs > 0 && s.p95Ms > 2.5 * s.medianMs) out.add(Finding(Sev.WARN, "BENCH_JITTER", "$label: p95 ${fmt1(s.p95Ms)} ms vs median ${fmt1(s.medianMs)} ms: thermal throttling or other load; rerun after cooling."))
    return out
}

/** Median of timings (copy-sorted); 0 for an empty list. */
fun medianOf(v: List<Double>): Double {
    if (v.isEmpty()) return 0.0
    val s = v.sorted(); val n = s.size
    return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2.0
}

/** First-run cost: how much slower the very first run was than the steady state (median of the rest). */
fun firstRunFinding(label: String, firstMs: Double, restMs: List<Double>): Finding? {
    val m = medianOf(restMs)
    if (m <= 0 || firstMs < 3 * m) return null
    return Finding(Sev.INFO, "FIRST_RUN_SLOW", "$label: first run ${fmt1(firstMs)} ms vs steady ${fmt1(m)} ms (x${fmt1(firstMs / m)}): graph compile/warm-up, expected once per session")
}

// ---------------------------------------------------------------- model contract

fun shapeText(s: LongArray): String = s.joinToString(",", "[", "]") { if (it <= 0) "?" else it.toString() }

/** Null when [got] fits [expected] (dims <= 0 are dynamic and match anything); else a short reason. */
fun shapeMismatch(expected: LongArray, got: LongArray): String? {
    if (expected.size != got.size) return "rank ${got.size} but model wants ${expected.size} (${shapeText(expected)})"
    for (i in expected.indices) if (expected[i] > 0 && expected[i] != got[i]) return "dim $i is ${got[i]} but model wants ${expected[i]} (${shapeText(expected)})"
    return null
}

/** What the pose runner feeds: exactly one input, an NCHW image batch (channels 3). */
fun looksLikePoseInput(inputs: Map<String, LongArray>): Boolean =
    inputs.size == 1 && inputs.values.first().let { it.size == 4 && it[1] == 3L }

/**
 * Checks a graph's declared inputs/outputs before the first run. [expectPose] = it will be used with `PoseRunner`.
 * Catches the phone error `ORT_INVALID_ARGUMENT ... image_embed index 1 Got: 3 Expected: 256` (a SAM graph picked in the pose bench).
 */
fun modelContractFindings(name: String, inputs: Map<String, LongArray>, outputs: Map<String, LongArray>, expectPose: Boolean): List<Finding> {
    val out = ArrayList<Finding>()
    val io = "in " + inputs.entries.joinToString(" ") { "${it.key}${shapeText(it.value)}" } + " out " + outputs.entries.joinToString(" ") { "${it.key}${shapeText(it.value)}" }
    out.add(Finding(Sev.INFO, "MODEL_IO", "$name: $io"))
    if (expectPose && !looksLikePoseInput(inputs)) {
        out.add(Finding(Sev.ERROR, "MODEL_NOT_POSE", "$name has inputs ${inputs.keys} but the pose runner feeds one [1,3,H,W] image: this graph is not a pose model (do not pick it in the pose bench)"))
        return out
    }
    for ((k, v) in inputs) if (v.any { it <= 0 }) out.add(Finding(Sev.WARN, "DYN_SHAPE", "$name input $k${shapeText(v)} has dynamic dims: QNN/HTP needs static shapes, expect CPU fallback"))
    if (expectPose) {
        val s = inputs.values.first()
        if (s[2] > 0 && (s[2] % 32L != 0L || s[3] % 32L != 0L)) out.add(Finding(Sev.WARN, "POSE_STRIDE", "$name input ${s[2]}x${s[3]} is not a multiple of 32: boxes may shift"))
        val o = outputs.values.firstOrNull()
        if (o == null || o.size != 3 || (o[1] != 56L && o[2] != 56L && o[1] != 51L && o[2] != 51L)) {
            out.add(Finding(Sev.WARN, "POSE_OUT", "$name output ${o?.let { shapeText(it) } ?: "none"} is not [1,56,N] / [1,N,56]: decodeYoloPose may read wrong data"))
        }
    }
    return out
}

/** Cosine similarity of two outputs (first min(size) values). 1.0 when both are all zero; NaN-safe: returns -1 if any value is not finite. */
fun cosine(a: FloatArray, b: FloatArray): Double {
    val n = minOf(a.size, b.size)
    var ab = 0.0; var aa = 0.0; var bb = 0.0
    for (i in 0 until n) {
        val x = a[i].toDouble(); val y = b[i].toDouble()
        if (x.isNaN() || y.isNaN() || x.isInfinite() || y.isInfinite()) return -1.0
        ab += x * y; aa += x * x; bb += y * y
    }
    if (aa == 0.0 && bb == 0.0) return 1.0
    return if (aa == 0.0 || bb == 0.0) 0.0 else ab / (sqrt(aa) * sqrt(bb))
}

/** NPU result vs CPU result of the same graph and input; below 0.99 the NPU (fp16/int8) output is not trustworthy. */
fun parityFinding(label: String, cos: Double): Finding? = when {
    cos < 0 -> Finding(Sev.ERROR, "NPU_NAN", "$label: NPU or CPU output contains NaN/Infinity")
    cos < 0.99 -> Finding(Sev.WARN, "NPU_PARITY", "$label: NPU output differs from CPU (cosine ${(Math.round(cos * 10000) / 10000.0)}); compare keypoints before trusting the NPU")
    else -> null
}

// ---------------------------------------------------------------- throughput / ETA

/**
 * Tracks ms per frame during a long job. The baseline is the median of the first [warm] frames after the very first one;
 * the smoothed value follows with weight [alpha]. A smoothed time well above the baseline = the phone is throttling or something else is competing.
 */
class Throughput(private val warm: Int = 8, private val alpha: Double = 0.1) {
    private val first = ArrayList<Double>()
    private var skipped = false
    var ewma = 0.0; private set
    var n = 0; private set
    val baseline: Double get() = if (first.size >= warm) medianOf(first) else 0.0

    fun add(ms: Double) {
        n++
        if (!skipped) { skipped = true; return } // frame 0 carries compile/warm-up
        if (first.size < warm) first.add(ms)
        ewma = if (ewma == 0.0) ms else ewma + alpha * (ms - ewma)
    }

    /** smoothed / baseline; 1.0 until the baseline exists. */
    val slowdown: Double get() = if (baseline > 0 && ewma > 0) ewma / baseline else 1.0

    fun etaS(remaining: Int): Double = if (ewma > 0) remaining.coerceAtLeast(0) * ewma / 1000.0 else -1.0

    /** thermal = PowerManager thermal status 0..6 (-1 unknown). */
    fun finding(remaining: Int, thermal: Int): Finding? {
        val sd = slowdown
        if (sd < 1.25) return null
        val hot = thermal >= 2
        if (sd < 1.5 && !hot) return null
        val eta = etaS(remaining)
        val cause = if (hot) "phone is hot (thermal $thermal)" else "no thermal signal: another app or memory pressure?"
        return Finding(Sev.PREDICT, "THROTTLE", "frames are x${fmt1(sd)} slower than at the start ($cause); ${if (eta >= 0) "about ${fmt1(eta / 60.0)} min left at this speed" else "ETA unknown"}. Let it cool or lower the scan fps.")
    }
}

// ---------------------------------------------------------------- trends (memory, battery, storage)

/** Least-squares line through (seconds, value). Returns slope per second, or null with fewer than 4 points / a span under [minSpanS]. */
fun slopePerS(points: List<Pair<Double, Double>>, minSpanS: Double = 20.0): Double? {
    if (points.size < 4) return null
    if (points.last().first - points.first().first < minSpanS) return null
    val n = points.size.toDouble()
    val mx = points.sumOf { it.first } / n
    val my = points.sumOf { it.second } / n
    var sxy = 0.0; var sxx = 0.0
    for ((x, y) in points) { sxy += (x - mx) * (y - my); sxx += (x - mx) * (x - mx) }
    return if (sxx <= 0) null else sxy / sxx
}

/** Seconds until a rising series reaches [limit] (null = not rising or unknown, 0 = already there). */
fun secondsToLimit(points: List<Pair<Double, Double>>, limit: Double): Double? {
    val sl = slopePerS(points) ?: return null
    val last = points.last().second
    if (last >= limit) return 0.0
    if (sl <= 1e-9) return null
    return (limit - last) / sl
}

/** Memory warning: [usedMb] samples (seconds, MB) against [limitMb] (Java heap max, or the low-memory threshold). */
fun memoryFinding(what: String, usedMb: List<Pair<Double, Double>>, limitMb: Double): Finding? {
    val last = usedMb.lastOrNull()?.second ?: return null
    if (limitMb > 0 && last >= 0.9 * limitMb) return Finding(Sev.WARN, "MEM_HIGH", "$what at ${fmt1(last)} of ${fmt1(limitMb)} MB (${(100 * last / limitMb).toInt()} %)")
    val t = secondsToLimit(usedMb, limitMb) ?: return null
    return if (t in 0.0..900.0) Finding(Sev.PREDICT, "MEM_LEAK", "$what grows toward its limit: ${fmt1(last)} of ${fmt1(limitMb)} MB, full in about ${(t / 60).toInt()} min ${(t % 60).toInt()} s (leak? bitmaps not recycled?)") else null
}

/** Battery: percent at start/now, [elapsedS] since start, [remainingS] of work left. */
fun batteryFinding(pctStart: Int, pctNow: Int, elapsedS: Double, charging: Boolean, remainingS: Double): Finding? {
    if (charging || elapsedS < 120 || pctStart < 0 || pctNow < 0 || remainingS <= 0) return null
    val perS = (pctStart - pctNow) / elapsedS
    if (perS <= 0) return null
    val lastsS = pctNow / perS
    if (lastsS >= remainingS * 1.1) return null
    return Finding(Sev.PREDICT, "BATTERY_DIES", "battery $pctNow %, falling ${fmt1(perS * 3600)} %/h; it lasts about ${fmt1(lastsS / 60)} min but ${fmt1(remainingS / 60)} min of work remain. Plug in.")
}

/** Storage: [need] bytes wanted, [free] bytes available (Long.MAX_VALUE = unknown, never a finding). */
fun storageFinding(what: String, free: Long, need: Long): Finding? {
    if (free == Long.MAX_VALUE || need <= 0) return null
    val mb = { b: Long -> b / (1024 * 1024) }
    return when {
        free < need -> Finding(Sev.PREDICT, "NO_SPACE", "$what needs about ${mb(need)} MB, ${mb(free)} MB free: it will fail")
        free < need * 3 / 2 -> Finding(Sev.WARN, "LOW_SPACE", "$what needs about ${mb(need)} MB, only ${mb(free)} MB free")
        else -> null
    }
}

// ---------------------------------------------------------------- data sanity

class TimelineStats(val n: Int, val nonMonotonic: Int, val duplicates: Int, val bigGaps: Int, val maxGapS: Double)

/** [ts] = sample times in order; a gap is more than 2.5 expected steps. */
fun timelineStats(ts: List<Double>, stepS: Double): TimelineStats {
    var back = 0; var dup = 0; var gaps = 0; var maxGap = 0.0
    for (i in 1 until ts.size) {
        val d = ts[i] - ts[i - 1]
        if (d < -1e-9) back++ else if (abs(d) <= 1e-9) dup++ else if (stepS > 0 && d > 2.5 * stepS) { gaps++; if (d > maxGap) maxGap = d }
    }
    return TimelineStats(ts.size, back, dup, gaps, maxGap)
}

fun timelineFindings(label: String, s: TimelineStats): List<Finding> {
    val out = ArrayList<Finding>()
    if (s.nonMonotonic > 0) out.add(Finding(Sev.ERROR, "TIME_BACKWARDS", "$label: ${s.nonMonotonic} samples go back in time (decoder timestamps out of order)"))
    if (s.duplicates > 0) out.add(Finding(Sev.WARN, "TIME_DUP", "$label: ${s.duplicates} samples repeat the same time (decoder returned one frame twice)"))
    if (s.bigGaps > 0) out.add(Finding(Sev.WARN, "TIME_GAPS", "$label: ${s.bigGaps} gaps, longest ${fmt1(s.maxGapS)} s (frames skipped; the follow camera will hold or jump)"))
    return out
}

/** Share of values below [thr] (confidence) and non-finite count, e.g. keypoint confidences of the chosen target. */
fun lowConfFinding(label: String, v: List<Double>, thr: Double = 0.3): Finding? {
    if (v.isEmpty()) return Finding(Sev.WARN, "NO_DATA", "$label: no values at all")
    val bad = v.count { it.isNaN() || it.isInfinite() }
    if (bad > 0) return Finding(Sev.ERROR, "NAN", "$label: $bad of ${v.size} values are NaN/Infinity")
    val low = v.count { it < thr }
    val share = low.toDouble() / v.size
    return if (share >= 0.5) Finding(Sev.PREDICT, "LOW_CONF", "$label: ${(share * 100).toInt()} % of values are below $thr: the target will be lost often (try a bigger model, higher scan fps, or another part)") else null
}

/** Jump check on positions (x, y) in pixels: share of steps longer than [maxStepPx]. */
fun jumpFinding(label: String, xs: List<Double>, ys: List<Double>, maxStepPx: Double): Finding? {
    val n = minOf(xs.size, ys.size)
    if (n < 3) return null
    var jumps = 0
    for (i in 1 until n) { val dx = xs[i] - xs[i - 1]; val dy = ys[i] - ys[i - 1]; if (sqrt(dx * dx + dy * dy) > maxStepPx) jumps++ }
    return if (jumps * 10 >= n - 1 && jumps >= 3) Finding(Sev.PREDICT, "JUMPY", "$label: $jumps of ${n - 1} steps jump over ${fmt1(maxStepPx)} px (ID switch or bad detections; the zoom will shake)") else null
}

// ---------------------------------------------------------------- Debug Part 2: target, decode, export

/**
 * Checks the picked target of a finished scan: keypoint confidence of the target's joints (LOW_CONF / NAN), how often the
 * person ID is present at all (TARGET_ABSENT) and jumps of the follow-camera centre between samples (JUMPY, cuts skipped).
 * Whole-person and free-point targets have no joints: only presence and jumps are checked.
 */
fun targetFindings(doc: TrackDoc): List<Finding> {
    val tg = doc.target ?: return emptyList()
    val out = ArrayList<Finding>()
    val ids = (listOf(tg.id) + tg.linked).filter { it >= 0 }
    val joints = tg.part?.let { listOf(it) } ?: tg.preset?.let { PRESETS[it]?.toList() }.orEmpty()
    val n = doc.samples.size
    if (n == 0) return emptyList()
    if (ids.isNotEmpty()) {
        val present = doc.samples.count { s -> ids.any { id -> s.kp?.containsKey(id.toString()) == true || s.d.any { it.isNotEmpty() && it[0].toInt() == id } } }
        if (present * 2 < n) out.add(Finding(Sev.PREDICT, "TARGET_ABSENT", "person #${tg.id} is in only $present of $n samples: the follow camera will hold still most of the time (wrong ID picked, or the person leaves the frame)"))
        if (joints.isNotEmpty()) {
            val conf = ArrayList<Double>()
            for (s in doc.samples) for (id in ids) for (j in joints) s.keypoint(id, j)?.let { conf.add(it.conf) }
            if (conf.isNotEmpty()) lowConfFinding("target joints ${joints.joinToString(",")}", conf)?.let { out.add(it) }
        }
    }
    val w = doc.video.w.takeIf { it > 0 }?.toDouble() ?: 1.0
    val v = doc.views
    if (v.size >= 4) {
        var jumps = 0; var steps = 0
        for (i in 1 until v.size) {
            if (v[i].size < 4 || v[i - 1].size < 4) continue
            if (doc.cuts.any { it > v[i - 1][0] && it <= v[i][0] }) continue
            steps++
            val dx = v[i][2] - v[i - 1][2]; val dy = v[i][3] - v[i - 1][3]
            if (sqrt(dx * dx + dy * dy) > 0.25) jumps++ // pan is normalized: a quarter of the frame in one sample
        }
        if (steps >= 3 && jumps >= 3 && jumps * 10 >= steps) out.add(Finding(Sev.PREDICT, "JUMPY", "follow camera jumps over a quarter of the frame in $jumps of $steps steps (ID switch or bad detections; the zoom will shake)"))
    }
    return out
}

/** Decoder health from per-frame times: slow frames, missed frames (retriever returned null), nothing decoded. */
fun decodeFindings(label: String, frameMs: List<Double>, delivered: Int, misses: Int): List<Finding> {
    val out = ArrayList<Finding>()
    if (delivered == 0) { out.add(Finding(Sev.ERROR, "DECODE_NONE", "$label: no frame could be decoded (corrupt/unsupported clip, or the file is no longer readable)")); return out }
    val m = medianOf(frameMs)
    if (m > 300.0) out.add(Finding(Sev.PREDICT, "DECODE_SLOW", "$label: median ${fmt1(m)} ms per frame just to decode: long clips will take very long (4K/HEVC/HDR source; lower the scan fps)"))
    if (misses > 0) out.add(Finding(Sev.WARN, "DECODE_MISS", "$label: $misses frame requests returned nothing (sparse keyframes or damaged stream); the scan timeline will have gaps"))
    return out
}

/** Export that stopped moving: [history] = (seconds since start, progress 0..1) samples, newest last. */
fun progressStallFinding(label: String, history: List<Pair<Double, Double>>, stallS: Double = 45.0): Finding? {
    if (history.size < 2) return null
    val last = history.last()
    if (last.second >= 0.999 || last.second < 0.0) return null
    val since = history.lastOrNull { abs(it.second - last.second) > 1e-4 }?.first ?: history.first().first
    val stalled = last.first - since
    return if (stalled >= stallS) Finding(Sev.PREDICT, "EXPORT_STALL", "$label: progress stuck at ${(last.second * 100).toInt()} % for ${fmt1(stalled)} s (encoder hung or screen off/throttled; keep the app open)") else null
}

/** Speed of a finished export or scan as x realtime; slow runs get a WARN so they stand out in the report. */
fun speedFinding(label: String, xRealtime: Double, warnBelow: Double): Finding =
    if (xRealtime > 0 && xRealtime < warnBelow) Finding(Sev.WARN, "SLOW_RUN", "$label ran at ${fmt1(xRealtime)} x realtime (below ${fmt1(warnBelow)}): check thermal/battery lines above")
    else Finding(Sev.INFO, "SPEED", "$label ${fmt1(xRealtime)} x realtime")

// ---------------------------------------------------------------- log text

/** `time | where | LEVEL | message`, same shape as [logLine] so one parser reads the whole error log. */
fun eventLine(time: String, where: String, level: String, message: String): String =
    "$time | $where | $level | " + message.replace("\r", "").replace('\n', ' ').replace("  ", " ").take(600)

/**
 * Collapses repeated log lines (same text after the timestamp) into one: `first-time | rest  (xN, last HH:mm:ss)`.
 * Keeps the order of first appearance. A pasted log then costs far fewer tokens.
 */
fun dedupeLog(text: String): String {
    class G(val first: String, var last: String, var n: Int)
    val groups = LinkedHashMap<String, G>()
    for (raw in text.lineSequence()) {
        if (raw.isBlank()) continue
        val i = raw.indexOf(" | ")
        val time = if (i > 0) raw.substring(0, i) else ""
        val rest = if (i > 0) raw.substring(i + 3) else raw
        val g = groups[rest]
        if (g == null) groups[rest] = G(time, time, 1) else { g.last = time; g.n++ }
    }
    return groups.entries.joinToString("\n") { (rest, g) ->
        val head = if (g.first.isEmpty()) rest else "${g.first} | $rest"
        if (g.n > 1) "$head  (x${g.n}, last ${g.last.substringAfter(' ')})" else head
    }
}

/**
 * Builds a report from ordered sections (most important first). The first section is always complete; later sections get what is
 * left of [maxChars], each keeping its END (newest lines) via [trimLog]; sections that do not fit at all are listed as omitted.
 */
fun buildReport(sections: List<Pair<String, String>>, maxChars: Int): String {
    val sb = StringBuilder()
    val omitted = ArrayList<String>()
    for ((i, sec) in sections.withIndex()) {
        val (title, body) = sec
        if (body.isBlank()) continue
        val head = "=== $title ===\n"
        val room = if (i == 0) Int.MAX_VALUE else maxChars - sb.length - head.length - 1
        if (room < 80) { omitted.add(title); continue }
        sb.append(head).append(if (body.length <= room) body else "(cut)\n" + trimLog(body, room - 6)).append('\n')
    }
    if (omitted.isNotEmpty()) sb.append("(omitted for size: ${omitted.joinToString()}; use Save full report)\n")
    return sb.toString()
}

/** Unique WARN/PREDICT/ERROR lines (ERROR first), newest occurrence kept, for the top of a compact report. */
fun topFindings(lines: List<String>, max: Int = 12): List<String> {
    val kinds = listOf(" | NO_SPACE | ", " | MODEL_MISSING | ", " | VIDEO_ACCESS | ", " | CODEC | ", " | OTHER | ") // exception lines of the old error log
    fun rank(l: String) = when { " ERROR " in l || kinds.any { it in l } -> 0; " PREDICT " in l -> 1; " WARN " in l -> 2; else -> 3 }
    return lines.filter { rank(it) < 3 }.asReversed().distinctBy { it.substringAfter(" | ") }.sortedBy { rank(it) }.take(max)
}
