package com.takipli.oynat

import ai.onnxruntime.OnnxJavaType
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import ai.onnxruntime.TensorInfo
import android.app.Activity
import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.app.Application
import android.content.ComponentCallbacks2
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.res.Configuration
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.Debug
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import com.takipli.oynat.core.BenchStats
import com.takipli.oynat.core.Finding
import com.takipli.oynat.core.Sev
import com.takipli.oynat.core.Throughput
import com.takipli.oynat.core.batteryFinding
import com.takipli.oynat.core.benchFindings
import com.takipli.oynat.core.benchStats
import com.takipli.oynat.core.buildReport
import com.takipli.oynat.core.cosine
import com.takipli.oynat.core.dedupeLog
import com.takipli.oynat.core.eventLine
import com.takipli.oynat.core.firstRunFinding
import com.takipli.oynat.core.fmt1
import com.takipli.oynat.core.memoryFinding
import com.takipli.oynat.core.modelContractFindings
import com.takipli.oynat.core.parityFinding
import com.takipli.oynat.core.shapeText
import com.takipli.oynat.core.storageFinding
import com.takipli.oynat.core.timelineFindings
import com.takipli.oynat.core.timelineStats
import com.takipli.oynat.core.topFindings
import com.takipli.oynat.core.trimLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.ByteBuffer
import java.nio.FloatBuffer
import java.nio.IntBuffer
import java.nio.LongBuffer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.Random
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

/**
 * Debug Part 1: predictive debugging for the error log. Everything lands in the same log files the Share button already sends
 * (`files/logs/error.log` for WARN/PREDICT/ERROR, `files/logs/diag.log` for telemetry), so one paste carries the whole story.
 * Rule: nothing in here may ever throw into the app (every public entry is wrapped).
 */
object Diag {
    private const val DIAG_MAX = 60_000
    private val LAST_RUN = Regex(" \\| (SCAN_|EXPORT_|DECODE_|SLOW_RUN|SPEED|FIRST_FRAME|PICK_|TARGET_|JUMPY|LOW_CONF|PLAYER_|NO_PEOPLE)")
    private val lock = Any()
    @Volatile private var foreground = false
    private var started = 0

    private fun stamp() = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(Date())
    private fun logDir(ctx: Context) = File(ctx.filesDir, "logs")
    private fun diagFile(ctx: Context) = File(logDir(ctx), "diag.log")
    private fun selfFile(ctx: Context) = File(logDir(ctx), "selfcheck.txt")
    private fun prevLogcatFile(ctx: Context) = File(logDir(ctx), "prev-logcat.txt")

    // ------------------------------------------------------------ events

    /** Writes one finding. INFO goes to diag.log only; WARN/PREDICT/ERROR go to error.log as well. */
    fun event(ctx: Context, where: String, f: Finding) {
        runCatching {
            val line = eventLine(stamp(), where, f.sev.name, "${f.code} ${f.msg}")
            synchronized(lock) {
                val d = diagFile(ctx)
                d.parentFile?.mkdirs()
                d.writeText(trimLog((if (d.isFile) d.readText() else "") + line + "\n", DIAG_MAX))
            }
            if (f.sev != Sev.INFO) ErrorLog.appendLine(ctx, line)
        }
    }

    fun note(ctx: Context, where: String, code: String, msg: String, sev: Sev = Sev.INFO) = event(ctx, where, Finding(sev, code, msg))

    // ------------------------------------------------------------ vitals and snapshot

    fun thermal(ctx: Context): Int = runCatching { ctx.getSystemService(PowerManager::class.java).currentThermalStatus }.getOrDefault(-1)

    /** (percent or -1, charging, temperature in degrees C or -1.0) */
    fun battery(ctx: Context): Triple<Int, Boolean, Double> {
        val i = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return Triple(-1, false, -1.0)
        val level = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        val st = i.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val temp = i.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
        return Triple(
            if (level >= 0 && scale > 0) level * 100 / scale else -1,
            st == BatteryManager.BATTERY_STATUS_CHARGING || st == BatteryManager.BATTERY_STATUS_FULL,
            if (temp == Int.MIN_VALUE) -1.0 else temp / 10.0,
        )
    }

    private fun memInfo(ctx: Context): ActivityManager.MemoryInfo =
        ActivityManager.MemoryInfo().also { ctx.getSystemService(ActivityManager::class.java).getMemoryInfo(it) }

    /** One short line: what the phone looked like at this moment. Appended to every error line. */
    fun vitals(ctx: Context): String = runCatching {
        val rt = Runtime.getRuntime()
        val mi = memInfo(ctx)
        val (pct, chg, temp) = battery(ctx)
        "heap ${(rt.totalMemory() - rt.freeMemory()) shr 20}/${rt.maxMemory() shr 20} MB, native ${Debug.getNativeHeapAllocatedSize() shr 20} MB, " +
            "ram free ${mi.availMem shr 20} MB${if (mi.lowMemory) " LOW" else ""}, thermal ${thermal(ctx)}, bat $pct%${if (chg) "+" else ""} ${fmt1(temp)}C, " +
            "disk ${Safety.freeBytes(ctx.filesDir).let { if (it == Long.MAX_VALUE) -1 else it shr 20 }} MB, thr ${Thread.activeCount()}"
    }.getOrDefault("vitals n/a")

    private fun dirSize(f: File): Long = if (f.isFile) f.length() else f.listFiles()?.sumOf { dirSize(it) } ?: 0L

    /** Multi-line description of the device, the app and its files. */
    fun snapshot(ctx: Context, deep: Boolean = true): String = buildString {
        fun line(s: String) = appendLine(s)
        runCatching {
            line("app ${BuildConfig.VERSION_NAME} build ${BuildConfig.BUILD_NUMBER} engine ${BuildConfig.ENGINE} | uptime ${(SystemClock.elapsedRealtime() / 1000)} s since boot")
            val soc = if (Build.VERSION.SDK_INT >= 31) " soc ${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}" else ""
            line("device ${Build.MANUFACTURER} ${Build.MODEL} (${Build.DEVICE})$soc | Android ${Build.VERSION.RELEASE} API ${Build.VERSION.SDK_INT} patch ${Build.VERSION.SECURITY_PATCH} | abi ${Build.SUPPORTED_ABIS.joinToString()} | cores ${Runtime.getRuntime().availableProcessors()}")
        }
        runCatching { line("now: ${vitals(ctx)}") }
        runCatching {
            val mi = memInfo(ctx)
            val am = ctx.getSystemService(ActivityManager::class.java)
            line("ram total ${mi.totalMem shr 20} MB, low-mem threshold ${mi.threshold shr 20} MB, app limit ${am.memoryClass} MB (large ${am.largeMemoryClass} MB), pss ${Debug.MemoryInfo().also { Debug.getMemoryInfo(it) }.totalPss / 1024} MB")
            val pm = ctx.getSystemService(PowerManager::class.java)
            line("power-save ${pm.isPowerSaveMode} | sustained-perf ${pm.isSustainedPerformanceModeSupported} | thermal headroom ${if (Build.VERSION.SDK_INT >= 30) fmt1(pm.getThermalHeadroom(10).toDouble()) else "n/a"}")
        }
        runCatching {
            line("storage free: files ${Safety.freeBytes(ctx.filesDir) shr 20} MB, cache ${Safety.freeBytes(ctx.cacheDir) shr 20} MB | used: models ${dirSize(File(ctx.filesDir, "models")) shr 20} MB, qnn_ctx ${dirSize(File(ctx.filesDir, "qnn_ctx")) shr 20} MB, scans ${dirSize(File(ctx.filesDir, "scans")) shr 20} MB, cache ${dirSize(ctx.cacheDir) shr 20} MB")
        }
        runCatching {
            val libs = File(ctx.applicationInfo.nativeLibraryDir).listFiles { f -> f.name.contains("Qnn") || f.name.contains("onnxruntime") || f.name.contains("opencv") }
                ?.sortedBy { it.name }?.joinToString { "${it.name}:${it.length() shr 10}K" }.orEmpty()
            line("native libs: ${libs.ifEmpty { "none found in ${ctx.applicationInfo.nativeLibraryDir}" }}")
        }
        if (deep) runCatching { line("ort providers: ${OrtEnvironment.getAvailableProviders().joinToString()} | opencv ${if (OpenCvFlow.available) "ok" else "NOT loaded"}") }
        runCatching {
            line("models: " + ModelStore.list(ctx).joinToString { n ->
                val side = ctx.getExternalFilesDir("models")?.resolve(n)?.takeIf { it.isFile }
                val sz = side?.length() ?: runCatching { ctx.assets.openFd("models/$n").use { it.length } }.getOrDefault(-1L)
                "$n ${sz shr 20}MB${if (side != null) " (side-loaded)" else ""}"
            })
            line("qnn ctx cache: " + File(ctx.filesDir, "qnn_ctx").listFiles()?.joinToString { "${it.name.take(24)}:${it.length() shr 20}MB" }.orEmpty().ifEmpty { "empty" })
        }
        runCatching { line("pending scan data: " + File(ctx.filesDir, "scans").listFiles()?.joinToString { "${it.name.take(12)}:${it.length() shr 10}K" }.orEmpty().ifEmpty { "none" }) }
    }

    // ------------------------------------------------------------ previous process exits (native crashes, OOM kills, ANRs)

    private fun reasonName(r: Int): String = when (r) {
        ApplicationExitInfo.REASON_ANR -> "ANR"
        ApplicationExitInfo.REASON_CRASH -> "CRASH"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "CRASH_NATIVE"
        ApplicationExitInfo.REASON_DEPENDENCY_DIED -> "DEPENDENCY_DIED"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "EXCESSIVE_RESOURCE_USAGE"
        ApplicationExitInfo.REASON_EXIT_SELF -> "EXIT_SELF"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "INIT_FAILURE"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "LOW_MEMORY_KILL"
        ApplicationExitInfo.REASON_PERMISSION_CHANGE -> "PERMISSION_CHANGE"
        ApplicationExitInfo.REASON_SIGNALED -> "SIGNALED"
        ApplicationExitInfo.REASON_USER_REQUESTED -> "USER_REQUESTED"
        ApplicationExitInfo.REASON_USER_STOPPED -> "USER_STOPPED"
        else -> "REASON_$r"
    }

    private val BAD_EXITS = setOf("ANR", "CRASH", "CRASH_NATIVE", "EXCESSIVE_RESOURCE_USAGE", "INIT_FAILURE", "LOW_MEMORY_KILL", "SIGNALED", "DEPENDENCY_DIED")

    /** Why the previous processes of this app died (API 30+). A native crash in ORT/QNN never reaches the Java crash handler: this is where it shows. */
    fun exits(ctx: Context, max: Int = 6): String {
        if (Build.VERSION.SDK_INT < 30) return "n/a (needs Android 11+)"
        return runCatching {
            ctx.getSystemService(ActivityManager::class.java).getHistoricalProcessExitReasons(ctx.packageName, 0, max).joinToString("\n") { e ->
                "${SimpleDateFormat("MM-dd HH:mm:ss", Locale.ROOT).format(Date(e.timestamp))} | ${reasonName(e.reason)} | status ${e.status} | pss ${e.pss / 1024} MB rss ${e.rss / 1024} MB | ${e.description.orEmpty()}"
            }
        }.getOrDefault("unavailable")
    }

    /** At start: turns each NEW bad exit (since the last start) into an ERROR/WARN event, and keeps an ANR trace head. */
    private fun recordNewExits(ctx: Context) {
        if (Build.VERSION.SDK_INT < 30) return
        runCatching {
            val prefs = ctx.getSharedPreferences("diag", Context.MODE_PRIVATE)
            val seen = prefs.getLong("last_exit_ts", 0L)
            val list = ctx.getSystemService(ActivityManager::class.java).getHistoricalProcessExitReasons(ctx.packageName, 0, 8)
            var newest = seen
            for (e in list.sortedBy { it.timestamp }) {
                if (e.timestamp <= seen) continue
                newest = maxOf(newest, e.timestamp)
                val name = reasonName(e.reason)
                if (name !in BAD_EXITS) continue
                var extra = ""
                if (e.reason == ApplicationExitInfo.REASON_ANR) {
                    extra = runCatching { e.traceInputStream?.bufferedReader()?.use { it.readText().take(1500) } }.getOrNull().orEmpty()
                }
                val sev = if (name == "CRASH" || name == "CRASH_NATIVE" || name == "INIT_FAILURE") Sev.ERROR else Sev.WARN
                note(ctx, "prev-exit", "PREV_EXIT", "$name at ${SimpleDateFormat("MM-dd HH:mm:ss", Locale.ROOT).format(Date(e.timestamp))}, pss ${e.pss / 1024} MB, rss ${e.rss / 1024} MB, status ${e.status}, ${e.description.orEmpty()}" +
                    (Trace.read(ctx).lines().filter { it.isNotBlank() }.takeLast(3).joinToString(" / ").let { if (it.isEmpty()) "" else " | last steps: $it" }) +
                    (if (extra.isNotEmpty()) " | anr: $extra" else ""), sev)
            }
            if (newest > seen) prefs.edit().putLong("last_exit_ts", newest).apply()
        }
    }

    // ------------------------------------------------------------ logcat (own process only; native ORT/QNN/MediaCodec warnings land here)

    fun logcat(lines: Int = 300, maxChars: Int = 6000): String = runCatching {
        val p = ProcessBuilder("logcat", "-d", "-t", lines.toString(), "-v", "time", "*:W").redirectErrorStream(true).start()
        val txt = p.inputStream.bufferedReader().use { it.readText() }
        runCatching { p.destroy() }
        trimLog(txt.lines().filterNot { it.startsWith("---") || it.isBlank() }.joinToString("\n"), maxChars)
    }.getOrDefault("")

    // ------------------------------------------------------------ install (called from App.onCreate)

    fun install(app: Application) {
        runCatching {
            app.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
                override fun onActivityCreated(a: Activity, s: Bundle?) { Trace.step(app, "act:create") }
                override fun onActivityStarted(a: Activity) { started++; foreground = true; Trace.step(app, "act:start") }
                override fun onActivityResumed(a: Activity) { Trace.step(app, "act:resume") }
                override fun onActivityPaused(a: Activity) { Trace.step(app, "act:pause") }
                override fun onActivityStopped(a: Activity) {
                    started--; Trace.step(app, "act:stop")
                    if (started <= 0) { foreground = false; thread(name = "diag-persist", isDaemon = true) { persistReport(app) } } // second channel: a file you can pull from the phone
                }
                override fun onActivitySaveInstanceState(a: Activity, s: Bundle) {}
                override fun onActivityDestroyed(a: Activity) { Trace.step(app, "act:destroy") }
            })
        }
        runCatching {
            app.registerComponentCallbacks(object : ComponentCallbacks2 {
                override fun onTrimMemory(level: Int) {
                    if (level < ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW || level == ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN) return
                    note(app, "memory", "TRIM_MEMORY", "level $level (${if (level >= 15) "critical" else "low"}) | ${vitals(app)}", Sev.WARN)
                }
                override fun onConfigurationChanged(c: Configuration) {}
                @Deprecated("only for old APIs") override fun onLowMemory() { note(app, "memory", "LOW_MEMORY", vitals(app), Sev.WARN) }
            })
        }
        runCatching {
            if (Build.VERSION.SDK_INT >= 29) {
                app.getSystemService(PowerManager::class.java).addThermalStatusListener({ it.run() }) { st ->
                    if (st >= PowerManager.THERMAL_STATUS_MODERATE) note(app, "thermal", "THERMAL", "status $st (moderate=2, severe=3, critical=4) | ${vitals(app)}", Sev.WARN)
                    else note(app, "thermal", "THERMAL", "status $st")
                }
            }
        }
        thread(name = "diag-boot", isDaemon = true) {
            // Order matters: read the logcat of the previous run before this run writes much into it.
            runCatching {
                val f = prevLogcatFile(app); f.parentFile?.mkdirs(); f.writeText(logcat(400, 12_000))
            }
            recordNewExits(app)
            note(app, "boot", "START", vitals(app))
        }
        startWatchdog(app)
    }

    /** Detects a blocked main thread (the thing that becomes an ANR at 5 s) and records WHERE it is stuck. */
    private fun startWatchdog(app: Application) {
        val h = Handler(Looper.getMainLooper())
        val mainThread = Looper.getMainLooper().thread
        val ack = AtomicLong(SystemClock.elapsedRealtime())
        thread(name = "diag-watchdog", isDaemon = true) {
            var reported = 0
            while (true) {
                val sent = SystemClock.elapsedRealtime()
                h.post { ack.set(SystemClock.elapsedRealtime()) }
                try { Thread.sleep(1000) } catch (_: InterruptedException) { return@thread }
                if (ack.get() >= sent || !foreground) continue
                val stack = mainThread.stackTrace.take(8).joinToString(" <- ") { "${it.className.substringAfterLast('.')}.${it.methodName}:${it.lineNumber}" }
                while (ack.get() < sent && SystemClock.elapsedRealtime() - sent < 20_000) Thread.sleep(200)
                val ms = SystemClock.elapsedRealtime() - sent
                if (reported++ < 15) note(app, "watchdog", "MAIN_STALL", "main thread blocked ~$ms ms (ANR at 5000) at $stack", Sev.WARN)
            }
        }
    }

    // ------------------------------------------------------------ crash context

    /** Called by the crash handler right after the error line: threads, main-thread stack and vitals at the moment of death. */
    fun crashContext(app: Application, t: Throwable) {
        runCatching {
            val main = Looper.getMainLooper().thread.stackTrace.take(6).joinToString(" <- ") { "${it.className.substringAfterLast('.')}.${it.methodName}:${it.lineNumber}" }
            val oom = t is OutOfMemoryError || t.cause is OutOfMemoryError
            note(app, "crash-context", "CRASH_CTX", "${if (oom) "OUT OF MEMORY | " else ""}${vitals(app)} | main: $main | last steps: ${Trace.read(app).lines().filter { it.isNotBlank() }.takeLast(3).joinToString(" / ")}", Sev.ERROR)
            persistReport(app, live = false)
        }
    }

    // ------------------------------------------------------------ models and benchmarks

    /**
     * Compares a session's declared inputs/outputs with what the caller will feed. Logs MODEL_IO and any finding; returns the
     * message when the graph can not work for [expectPose] (caller throws it instead of letting ORT fail with ORT_INVALID_ARGUMENT).
     */
    fun contract(ctx: Context, name: String, s: OrtSession, expectPose: Boolean): String? = runCatching {
        fun shapes(m: Map<String, ai.onnxruntime.NodeInfo>) = m.mapValues { (it.value.info as? TensorInfo)?.shape ?: longArrayOf() }
        val fs = modelContractFindings(name, shapes(s.inputInfo), shapes(s.outputInfo), expectPose)
        fs.forEach { event(ctx, "model", it) }
        fs.firstOrNull { it.sev == Sev.ERROR }?.msg
    }.getOrNull()

    fun bench(ctx: Context, label: String, stats: BenchStats, warmupMs: List<Double>) {
        runCatching {
            note(ctx, "bench", "BENCH", "$label n=${stats.n} mean ${fmt1(stats.meanMs)} median ${fmt1(stats.medianMs)} p95 ${fmt1(stats.p95Ms)} max ${fmt1(stats.maxMs)} ms | ${vitals(ctx)}")
            benchFindings(label, stats).forEach { event(ctx, "bench", it) }
            if (warmupMs.size >= 2) firstRunFinding(label, warmupMs.first(), warmupMs.drop(1))?.let { event(ctx, "bench", it) }
            if (thermal(ctx) >= 2) note(ctx, "bench", "HOT_BENCH", "$label measured while thermal ${thermal(ctx)}: numbers are pessimistic", Sev.WARN)
        }
    }

    /** Predicts a storage failure before long work starts. */
    fun preflightStorage(ctx: Context, what: String, need: Long) {
        runCatching { storageFinding(what, Safety.freeBytes(ctx.filesDir), need)?.let { event(ctx, "preflight", it) } }
    }

    /** Checks decoder timestamps of a finished scan (backwards, duplicate, gaps). */
    fun checkTimeline(ctx: Context, times: List<Double>, stepS: Double) {
        runCatching { timelineFindings("scan timeline", timelineStats(times, stepS)).forEach { event(ctx, "scan", it) } }
    }

    // ------------------------------------------------------------ QNN preflight

    private val QNN_REQUIRED = listOf("libQnnHtp.so", "libQnnHtpV75Stub.so", "libQnnHtpV75Skel.so", "libQnnSystem.so")

    fun qnnPreflight(ctx: Context): List<Finding> {
        val dir = File(ctx.applicationInfo.nativeLibraryDir)
        val missing = QNN_REQUIRED.filter { !File(dir, it).isFile }
        val out = ArrayList<Finding>()
        if (missing.isNotEmpty()) out.add(Finding(Sev.WARN, "QNN_LIBS_MISSING", "not in $dir: ${missing.joinToString()} (NPU will fall back to CPU; check jniLibs packaging)"))
        else out.add(Finding(Sev.INFO, "QNN_LIBS_OK", "all of ${QNN_REQUIRED.joinToString()} present"))
        if (Build.VERSION.SDK_INT >= 31 && !Build.SOC_MODEL.contains("SM8650", true) && !Build.SOC_MODEL.contains("8 Gen 3", true))
            out.add(Finding(Sev.INFO, "SOC_NOT_V75", "SoC ${Build.SOC_MODEL}: the build asks for HTP v75 (Snapdragon 8 Gen 3); other chips may need another htp_arch"))
        return out
    }

    // ------------------------------------------------------------ self-check: run every model on CPU and NPU once, predict problems

    private fun dummy(env: OrtEnvironment, ti: TensorInfo, rnd: Random): OnnxTensor {
        val shape = ti.shape.map { if (it <= 0) 1L else it }.toLongArray()
        val n = shape.fold(1L) { a, b -> a * b }.toInt()
        return when (ti.type) {
            OnnxJavaType.FLOAT -> OnnxTensor.createTensor(env, FloatBuffer.wrap(FloatArray(n) { rnd.nextFloat() }), shape)
            OnnxJavaType.INT64 -> OnnxTensor.createTensor(env, LongBuffer.wrap(LongArray(n)), shape)
            OnnxJavaType.INT32 -> OnnxTensor.createTensor(env, IntBuffer.wrap(IntArray(n)), shape)
            OnnxJavaType.UINT8, OnnxJavaType.INT8, OnnxJavaType.BOOL -> OnnxTensor.createTensor(env, ByteBuffer.allocateDirect(n), shape, ti.type)
            else -> throw IllegalArgumentException("dummy input of type ${ti.type} not supported")
        }
    }

    /**
     * Part 1 "Self-check": no video, no photo, no picking. Opens every model on CPU and (when the QNN libs exist) on the NPU, reads
     * its declared shapes, feeds fixed pseudo-random input, times 1 first + 5 steady runs, and compares NPU with CPU output.
     * Every problem becomes a Finding with a code. Result text is returned and saved to `logs/selfcheck.txt` (part of the report).
     */
    suspend fun selfCheck(ctx: Context, onStatus: (String) -> Unit): String = withContext(Dispatchers.Default) {
        val out = StringBuilder()
        fun add(f: Finding) { out.appendLine(f.text()); event(ctx, "selfcheck", f) }
        val t0 = SystemClock.elapsedRealtime()
        runCatching {
            qnnPreflight(ctx).forEach(::add)
            storageFinding("model contexts + scans", Safety.freeBytes(ctx.filesDir), 600L shl 20)?.let(::add)
            val (pct, chg, _) = battery(ctx)
            if (pct in 0..19 && !chg) add(Finding(Sev.WARN, "BATTERY_LOW", "battery $pct %, self-check on NPU is heavy"))
            if (thermal(ctx) >= 2) add(Finding(Sev.WARN, "HOT", "thermal ${thermal(ctx)}: timings will be pessimistic"))
            add(Finding(Sev.INFO, "VITALS", vitals(ctx)))
        }
        val env = OrtEnvironment.getEnvironment()
        val haveQnn = QNN_REQUIRED.all { File(ctx.applicationInfo.nativeLibraryDir, it).isFile }
        for (name in ModelStore.list(ctx)) {
            val cpuOut = ArrayList<FloatArray>()
            for (npu in listOf(false, true)) {
                ensureActive()
                val prov = if (npu) "NPU" else "CPU"
                val label = "${name.removeSuffix(".onnx")} $prov"
                if (npu && !haveQnn) { add(Finding(Sev.INFO, "SKIP_NPU", "$label skipped: QNN libs missing")); continue }
                onStatus(label)
                Trace.step(ctx, "selfcheck $label")
                val tl = System.nanoTime()
                val file = ModelStore.materialize(ctx, name)
                val session = try {
                    if (npu) Qnn.npuSession(ctx, env, file, name, 4) else Qnn.cpuSession(env, file, 4)
                } catch (e: Throwable) {
                    add(Finding(if (npu) Sev.WARN else Sev.ERROR, "${prov}_LOAD_FAIL", "$label: ${e.javaClass.simpleName}: ${(e.message ?: "").take(220)}"))
                    continue
                }
                session.use { s ->
                    val loadMs = (System.nanoTime() - tl) / 1_000_000
                    val tensors = ArrayList<Pair<String, OnnxTensor>>()
                    try {
                        val bad = contract(ctx, name, s, expectPose = name.startsWith("yolo"))
                        if (bad != null) {
                            add(Finding(Sev.ERROR, "CONTRACT", "$label: $bad"))
                        } else {
                            val rnd = Random(7)
                            for ((k, ni) in s.inputInfo) tensors.add(k to dummy(env, ni.info as TensorInfo, rnd))
                            val feed = tensors.toMap()
                            val times = ArrayList<Double>()
                            var first = 0.0
                            var out0: FloatArray? = null
                            for (i in 0 until 6) {
                                ensureActive()
                                val t1 = System.nanoTime()
                                s.run(feed).use { r ->
                                    val ms = (System.nanoTime() - t1) / 1e6
                                    if (i == 0) first = ms else times.add(ms)
                                    if (i == 1) out0 = runCatching {
                                        val fb = (r.get(0) as OnnxTensor).floatBuffer
                                        FloatArray(minOf(fb.remaining(), 4096)).also { fb.get(it) }
                                    }.getOrNull()
                                }
                            }
                            val st = benchStats(times)
                            val o = out0
                            add(Finding(Sev.INFO, "PROBE", "$label load $loadMs ms | first ${fmt1(first)} | median ${fmt1(st.medianMs)} ms (max ${fmt1(st.maxMs)}) | out0 ${o?.size ?: "non-float"}"))
                            benchFindings(label, st).forEach(::add)
                            firstRunFinding(label, first, times)?.let(::add)
                            if (o != null) {
                                if (o.any { it.isNaN() || it.isInfinite() }) add(Finding(Sev.ERROR, "NAN_OUT", "$label: output has NaN/Infinity"))
                                if (!npu) {
                                    cpuOut.add(o)
                                } else {
                                    val c = cpuOut.firstOrNull()
                                    if (c != null) {
                                        val cs = cosine(c, o)
                                        val pf = parityFinding(label, cs)
                                        add(pf ?: Finding(Sev.INFO, "PARITY_OK", "$label matches CPU (cosine ${"%.4f".format(cs)})"))
                                    }
                                }
                            }
                        }
                    } catch (e: kotlinx.coroutines.CancellationException) {
                        throw e
                    } catch (e: Throwable) {
                        add(Finding(Sev.ERROR, "${prov}_RUN_FAIL", "$label: ${e.javaClass.simpleName}: ${(e.message ?: "").take(260)}"))
                    } finally {
                        tensors.forEach { runCatching { it.second.close() } }
                    }
                }
            }
        }
        add(Finding(Sev.INFO, "DONE", "self-check took ${(SystemClock.elapsedRealtime() - t0) / 1000} s | ${vitals(ctx)}"))
        val text = out.toString()
        runCatching { selfFile(ctx).apply { parentFile?.mkdirs() }.writeText(text) }
        text
    }

    // ------------------------------------------------------------ report (what Share / Copy / Save send)

    /**
     * Compact (about 9 KB, deduplicated, findings first) or full report. [live] = also read the logcat now (never from a crash handler).
     * Sections are in priority order; when the size limit bites, the lowest-priority sections lose their oldest lines first.
     */
    fun report(ctx: Context, full: Boolean, live: Boolean = true): String = runCatching {
        val errAll = ErrorLog.read(ctx)
        val diag = runCatching { diagFile(ctx).takeIf { it.isFile }?.readText().orEmpty() }.getOrDefault("")
        val head = "Takipli Oynat ${BuildConfig.VERSION_NAME} #${BuildConfig.BUILD_NUMBER} | ${Build.MANUFACTURER} ${Build.MODEL} | Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}) | ${stamp()}"
        val top = topFindings((errAll + "\n" + diag).lines().filter { it.isNotBlank() }.sorted(), 12).joinToString("\n")
        val sections = listOf(
            "report" to head + "\n" + vitals(ctx),
            "top findings (errors, predictions, warnings)" to top,
            // D5: scan/decode/export telemetry survives the size cut here (diag.log is trimmed from the old end in the compact report)
            "last scan / decode / export" to dedupeLog(diag.lines().filter { LAST_RUN.containsMatchIn(it) }.joinToString("\n")).lines().takeLast(10).joinToString("\n"),
            "error log (deduplicated)" to dedupeLog(errAll),
            "previous process exits" to exits(ctx),
            "last self-check" to runCatching { selfFile(ctx).takeIf { it.isFile }?.readText().orEmpty() }.getOrDefault(""),
            "device" to snapshot(ctx, deep = live),
            "last video trace" to Trace.read(ctx).takeLast(if (full) 8000 else 1200),
            "telemetry (diag.log, deduplicated)" to dedupeLog(diag),
            "logcat now (W/E)" to if (live) logcat(if (full) 600 else 120, if (full) 20_000 else 2500) else "",
            "logcat of the previous run" to runCatching { prevLogcatFile(ctx).takeIf { it.isFile }?.readText().orEmpty() }.getOrDefault("").let { if (full) it else it.takeLast(1500) },
        )
        buildReport(sections, if (full) 250_000 else 9_000)
    }.getOrElse { "report failed: ${it.javaClass.simpleName}: ${it.message}" }

    /** Second channel: `Android/data/<id>/files/logs/last-report.txt`, readable by USB or a file manager, no share dialog needed. */
    fun persistReport(ctx: Context, live: Boolean = true) {
        runCatching {
            val dir = ctx.getExternalFilesDir("logs") ?: return
            dir.mkdirs()
            File(dir, "last-report.txt").writeText(report(ctx, full = true, live = live))
        }
    }

    fun stampForFile(): String = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(Date())
}

/**
 * Watches one long scan and predicts trouble while it runs: slowdown/throttling, memory growth toward the limit, battery that will not last,
 * and where the time goes (decode vs pose vs analysis vs preview). Cheap: one sample every 5 s; telemetry line every 30 s.
 */
class ScanWatch(private val ctx: Context, private val tag: String, private val total: Int, private val fps: Double) {
    private val tp = Throughput()
    private val t0 = SystemClock.elapsedRealtime()
    private val heap = ArrayList<Pair<Double, Double>>()
    private val sys = ArrayList<Pair<Double, Double>>()
    private val bat0 = Diag.battery(ctx).first
    private var lastTick = t0
    private var lastTelemetry = t0
    private val lastFired = HashMap<String, Long>()
    private var n = 0
    private var poseMs = 0.0; private var anMs = 0.0; private var prevMs = 0.0; private var periodMs = 0.0

    init { Diag.note(ctx, tag, "SCAN_START", "total ~$total samples at $fps fps | ${Diag.vitals(ctx)}") }

    private fun fire(f: Finding) {
        val now = SystemClock.elapsedRealtime()
        if (now - (lastFired[f.code] ?: -999_999L) < 120_000L) return // each warning at most every 2 min
        lastFired[f.code] = now
        Diag.event(ctx, tag, f)
    }

    /** One call per scanned frame. All times in ms; [period] = time since the previous frame started (decode + everything). */
    fun frame(period: Double, pose: Double, analysis: Double, preview: Double, done: Int) {
        n++
        tp.add(period)
        poseMs += pose; anMs += analysis; prevMs += preview; periodMs += period
        val now = SystemClock.elapsedRealtime()
        if (now - lastTick < 5000) return
        lastTick = now
        runCatching {
            val s = (now - t0) / 1000.0
            val rt = Runtime.getRuntime()
            heap.add(s to (rt.totalMemory() - rt.freeMemory()) / 1048576.0)
            val mi = ctx.getSystemService(ActivityManager::class.java).let { am -> ActivityManager.MemoryInfo().also { am.getMemoryInfo(it) } }
            sys.add(s to (mi.totalMem - mi.availMem) / 1048576.0)
            val remaining = (total - done).coerceAtLeast(0)
            val th = Diag.thermal(ctx)
            tp.finding(remaining, th)?.let(::fire)
            memoryFinding("Java heap", heap, rt.maxMemory() / 1048576.0)?.let(::fire)
            memoryFinding("device RAM in use", sys, (mi.totalMem - mi.threshold) / 1048576.0)?.let(::fire)
            val (pct, chg, _) = Diag.battery(ctx)
            batteryFinding(bat0, pct, s, chg, tp.etaS(remaining).coerceAtLeast(0.0))?.let(::fire)
            if (now - lastTelemetry >= 30_000) {
                lastTelemetry = now
                val k = n.coerceAtLeast(1)
                val other = (periodMs / k - (poseMs + anMs + prevMs) / k).coerceAtLeast(0.0)
                Diag.note(ctx, tag, "SCAN_TICK", "$done/$total | frame ${fmt1(periodMs / k)} ms = pose ${fmt1(poseMs / k)} + analysis ${fmt1(anMs / k)} + preview ${fmt1(prevMs / k)} + decode/other ${fmt1(other)} | slow x${fmt1(tp.slowdown)} | eta ${fmt1(tp.etaS(remaining) / 60)} min | ${Diag.vitals(ctx)}")
                poseMs = 0.0; anMs = 0.0; prevMs = 0.0; periodMs = 0.0; n = 0
            }
        }
    }

    fun finish(ok: Boolean, note: String) {
        Diag.note(ctx, tag, if (ok) "SCAN_END" else "SCAN_ABORT", "$note | slow x${fmt1(tp.slowdown)} | ${Diag.vitals(ctx)}", if (ok) Sev.INFO else Sev.WARN)
    }
}
