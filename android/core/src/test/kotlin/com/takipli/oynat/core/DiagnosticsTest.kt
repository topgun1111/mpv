package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DiagnosticsTest {
    private fun stats(mean: Double, med: Double, p95: Double, max: Double, n: Int = 20) = BenchStats(n, mean, med, p95, 1.0, max)

    @Test
    fun npuEncoderLineFromThePhoneIsFlagged() { // "NPU 1196.7 ms (p95 598.3)"
        val f = benchFindings("encoder NPU", stats(1196.7, 391.0, 598.3, 12000.0))
        assertTrue(f.any { it.code == "BENCH_OUTLIER" })
        assertTrue(benchFindings("decoder CPU", stats(40.1, 40.0, 41.8, 43.0)).isEmpty())
        assertTrue(benchFindings("x", stats(10.0, 9.0, 12.0, 14.0, n = 3)).single().code == "BENCH_FEW")
        assertTrue(benchFindings("x", stats(50.0, 20.0, 60.0, 70.0)).any { it.code == "BENCH_JITTER" })
    }

    @Test
    fun firstRunCost() {
        assertNotNull(firstRunFinding("m", 900.0, listOf(100.0, 110.0, 105.0)))
        assertNull(firstRunFinding("m", 150.0, listOf(100.0, 110.0, 105.0)))
    }

    @Test
    fun samDecoderPickedInThePoseBenchIsCaught() {
        val sam = mapOf("image_embed" to longArrayOf(1, 256, 64, 64), "point_coords" to longArrayOf(1, 2, 2))
        assertTrue(modelContractFindings("sam-decoder.onnx", sam, emptyMap(), true).any { it.code == "MODEL_NOT_POSE" })
        val pose = mapOf("images" to longArrayOf(1, 3, 640, 640))
        val ok = modelContractFindings("yolov8s-pose.onnx", pose, mapOf("output0" to longArrayOf(1, 56, 8400)), true)
        assertTrue(ok.none { it.sev == Sev.WARN || it.sev == Sev.ERROR })
        assertTrue(modelContractFindings("p", mapOf("i" to longArrayOf(1, 3, -1, -1)), mapOf("o" to longArrayOf(1, 56, 10)), true).any { it.code == "DYN_SHAPE" })
        assertTrue(modelContractFindings("p", pose, mapOf("o" to longArrayOf(1, 84, 8400)), true).any { it.code == "POSE_OUT" })
    }

    @Test
    fun shapeMismatchMessages() {
        assertNull(shapeMismatch(longArrayOf(1, 3, -1, 640), longArrayOf(1, 3, 480, 640)))
        assertTrue(shapeMismatch(longArrayOf(1, 256), longArrayOf(1, 3))!!.contains("dim 1 is 3"))
        assertTrue(shapeMismatch(longArrayOf(1, 256), longArrayOf(1, 256, 1))!!.contains("rank"))
    }

    @Test
    fun throttleIsPredictedFromSlowdown() {
        val t = Throughput(warm = 5)
        t.add(900.0) // first frame: ignored
        repeat(5) { t.add(100.0) }
        assertEquals(100.0, t.baseline, 1e-9)
        assertNull(t.finding(100, 0))
        repeat(60) { t.add(220.0) }
        assertTrue(t.slowdown > 1.5)
        val f = t.finding(300, 3)!!
        assertEquals("THROTTLE", f.code)
        assertTrue(f.msg.contains("hot"))
    }

    @Test
    fun memoryGrowthPredictsFullHeap() {
        val pts = (0..10).map { it * 10.0 to 100.0 + it * 20.0 } // +2 MB/s
        val t = secondsToLimit(pts, 512.0)!!
        assertEquals(106.0, t, 1.0)
        assertEquals("MEM_LEAK", memoryFinding("Java heap", pts, 512.0)!!.code)
        assertNull(secondsToLimit((0..10).map { it * 10.0 to 100.0 }, 512.0)) // flat
        assertNull(secondsToLimit(pts.take(3), 512.0)) // too few points
        assertEquals("MEM_HIGH", memoryFinding("Java heap", listOf(0.0 to 480.0), 512.0)!!.code)
    }

    @Test
    fun batteryAndStorage() {
        val f = batteryFinding(50, 40, 600.0, false, 3600.0)!! // 10 % per 10 min: 24 min left, 60 min needed
        assertEquals("BATTERY_DIES", f.code)
        assertNull(batteryFinding(50, 40, 600.0, true, 3600.0))
        assertNull(batteryFinding(50, 40, 600.0, false, 600.0))
        assertEquals("NO_SPACE", storageFinding("export", 100L shl 20, 300L shl 20)!!.code)
        assertEquals("LOW_SPACE", storageFinding("export", 400L shl 20, 300L shl 20)!!.code)
        assertNull(storageFinding("export", 2000L shl 20, 300L shl 20))
        assertNull(storageFinding("export", Long.MAX_VALUE, 300L shl 20))
    }

    @Test
    fun timelineAndTargetData() {
        val s = timelineStats(listOf(0.0, 0.1, 0.2, 0.2, 0.15, 1.5), 0.1)
        assertEquals(1, s.nonMonotonic); assertEquals(1, s.duplicates); assertEquals(1, s.bigGaps)
        assertEquals(3, timelineFindings("scan", s).size)
        assertEquals("LOW_CONF", lowConfFinding("kp", List(10) { 0.1 })!!.code)
        assertNull(lowConfFinding("kp", List(10) { 0.9 }))
        assertEquals("NAN", lowConfFinding("kp", listOf(0.9, Double.NaN))!!.code)
        val xs = listOf(0.0, 500.0, 0.0, 500.0, 0.0, 500.0); val ys = List(6) { 0.0 }
        assertEquals("JUMPY", jumpFinding("t", xs, ys, 100.0)!!.code)
        assertNull(jumpFinding("t", listOf(0.0, 1.0, 2.0, 3.0), listOf(0.0, 0.0, 0.0, 0.0), 100.0))
    }

    @Test
    fun dedupeAndReport() {
        val log = "2026-11-15 08:00:01 | scan | WARN | slow\n2026-11-15 08:00:05 | scan | WARN | slow\n2026-11-15 08:00:09 | x | ERROR | boom\n2026-11-15 08:00:11 | scan | WARN | slow"
        val d = dedupeLog(log).lines()
        assertEquals(2, d.size)
        assertTrue(d[0].endsWith("(x3, last 08:00:11)"))
        assertEquals(listOf("2026-11-15 08:00:09 | x | ERROR | boom".replace(" | ", " | ")), topFindings(log.lines()).filter { " ERROR " in it })
        assertEquals(1, topFindings(listOf("2026-11-15 08:00:01 | scan | OTHER | IllegalStateException: x", "2026-11-15 08:00:02 | a | INFO | fine")).size)
        val r = buildReport(listOf("A" to "first", "B" to "x".repeat(500), "C" to "y".repeat(500)), 300)
        assertTrue(r.contains("=== A ===") && r.contains("omitted for size"))
        assertTrue(buildReport(listOf("A" to "first", "B" to ""), 100).none { it == 'B' })
    }

    @Test
    fun npuParity() {
        val a = floatArrayOf(1f, 2f, 3f)
        assertEquals(1.0, cosine(a, a), 1e-9)
        assertEquals(-1.0, cosine(a, floatArrayOf(1f, Float.NaN, 3f)), 1e-9)
        assertNull(parityFinding("enc", cosine(a, floatArrayOf(1f, 2f, 3.01f))))
        assertEquals("NPU_PARITY", parityFinding("enc", cosine(a, floatArrayOf(3f, 2f, 1f)))!!.code)
        assertEquals("NPU_NAN", parityFinding("enc", -1.0)!!.code)
    }

    private fun doc(samples: List<Sample>, target: Target?, views: List<ViewKey> = emptyList(), cuts: List<Double> = emptyList()) =
        TrackDoc(2, VideoInfo(w = 1000, h = 500), 10.0, samples, target, views, cuts = cuts)

    private fun kp(conf: Double) = List(17) { listOf(0.1, 0.1, conf) }.flatten()

    @Test
    fun lowConfidenceTargetJointsAreFlagged() {
        val low = (0 until 20).map { Sample(it * 0.1, listOf(listOf(1.0, 0.0, 0.0, 1.0, 1.0, 0.9)), mapOf("1" to kp(0.1))) }
        val f = targetFindings(doc(low, Target(1, preset = "left_arm")))
        assertTrue(f.any { it.code == "LOW_CONF" })
        val good = low.map { it.copy(kp = mapOf("1" to kp(0.9))) }
        assertTrue(targetFindings(doc(good, Target(1, preset = "left_arm"))).isEmpty())
    }

    @Test
    fun absentTargetAndJumpsAreFlagged() {
        val s = (0 until 20).map { Sample(it * 0.1, if (it < 3) listOf(listOf(1.0, 0.0, 0.0, 1.0, 1.0, 0.9)) else emptyList()) }
        assertTrue(targetFindings(doc(s, Target(1))).any { it.code == "TARGET_ABSENT" })
        val views = (0 until 20).map { listOf(it * 0.1, 1.0, if (it % 2 == 0) 0.0 else 0.6, 0.0) }
        val ok = (0 until 20).map { Sample(it * 0.1, listOf(listOf(1.0, 0.0, 0.0, 1.0, 1.0, 0.9))) }
        assertTrue(targetFindings(doc(ok, Target(1), views)).any { it.code == "JUMPY" })
        assertTrue(targetFindings(doc(ok, Target(1), views, cuts = views.map { it[0] })).none { it.code == "JUMPY" }) // every step is a cut
        assertTrue(targetFindings(doc(ok, null)).isEmpty())
    }

    @Test
    fun decodeAndExportFindings() {
        assertEquals("DECODE_NONE", decodeFindings("clip", emptyList(), 0, 5).single().code)
        assertTrue(decodeFindings("clip", listOf(500.0, 600.0, 550.0), 3, 0).any { it.code == "DECODE_SLOW" })
        assertTrue(decodeFindings("clip", listOf(20.0, 25.0), 2, 3).any { it.code == "DECODE_MISS" })
        assertTrue(decodeFindings("clip", listOf(20.0, 25.0), 2, 0).isEmpty())
        val stuck = listOf(0.0 to 0.0, 10.0 to 0.30, 30.0 to 0.30, 60.0 to 0.30, 80.0 to 0.30)
        assertEquals("EXPORT_STALL", progressStallFinding("export", stuck)!!.code)
        assertNull(progressStallFinding("export", listOf(0.0 to 0.0, 10.0 to 0.3, 20.0 to 0.5)))
        assertNull(progressStallFinding("export", listOf(0.0 to 0.5, 100.0 to 1.0)))
        assertEquals("SLOW_RUN", speedFinding("export", 0.1, 0.3).code)
        assertEquals("SPEED", speedFinding("export", 1.2, 0.3).code)
    }
}
