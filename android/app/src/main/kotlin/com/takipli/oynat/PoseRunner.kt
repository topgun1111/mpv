package com.takipli.oynat

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import ai.onnxruntime.TensorInfo
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import com.takipli.oynat.core.BBox
import com.takipli.oynat.core.nms
import com.takipli.oynat.core.BenchStats
import com.takipli.oynat.core.Pose
import com.takipli.oynat.core.benchStats
import com.takipli.oynat.core.decodeYoloPose
import com.takipli.oynat.core.letterboxLayout
import com.takipli.oynat.core.preprocessChw
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.FloatBuffer

/** Models available to the bench: APK assets `models/NAME.onnx` plus side-loaded `files/models/NAME.onnx`. */
object ModelStore {
    private const val DIR = "models"

    private fun sideDir(ctx: Context): File? = ctx.getExternalFilesDir(DIR)

    fun list(ctx: Context): List<String> {
        val assets = ctx.assets.list(DIR).orEmpty().filter { it.endsWith(".onnx") }
        val side = sideDir(ctx)?.listFiles { f -> f.isFile && f.name.endsWith(".onnx") }?.map { it.name }.orEmpty()
        return (assets + side).distinct().sorted()
    }

    /** A real file path for ORT. Side-loaded files win; asset copies are refreshed when the size differs. */
    fun materialize(ctx: Context, name: String): File {
        sideDir(ctx)?.resolve(name)?.takeIf { it.isFile }?.let { return it }
        val out = File(ctx.filesDir, "$DIR/$name")
        out.parentFile?.mkdirs()
        val size = runCatching { ctx.assets.openFd("$DIR/$name").use { it.length } }.getOrDefault(-1L)
        if (!out.isFile || size < 0 || out.length() != size) {
            ctx.assets.open("$DIR/$name").use { input -> out.outputStream().use { input.copyTo(it) } }
        }
        return out
    }
}

class PoseResult(
    val poses: List<Pose>,
    val preMs: Double,
    val inferMs: Double,
    val postMs: Double,
) {
    val totalMs: Double get() = preMs + inferMs + postMs
}

class BenchReport(
    val total: BenchStats,
    val pre: BenchStats,
    val infer: BenchStats,
    val post: BenchStats,
    val poses: Int,
)

private const val KP_OK = 0.35
private const val MIN_KPTS = 6

/** YOLO-pose through ONNX Runtime (CPU). One instance = one session; calls must not overlap. */
class PoseRunner(context: Context, val modelName: String, val threads: Int, val wantNpu: Boolean = false) : AutoCloseable {
    private val appCtx: Context = context.applicationContext
    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    private val inputName: String
    val inputH: Int
    val inputW: Int
    val loadMs: Long
    /** True when the session really runs on the Hexagon NPU (QNN HTP). */
    val npu: Boolean
    /** Why the NPU was not used although requested (null = not requested or fine). */
    val npuFallback: String?
    val modelMb: Double
    private var argb = IntArray(0)
    private val chw: FloatArray

    init {
        val t0 = System.nanoTime()
        val file = ModelStore.materialize(context, modelName)
        modelMb = file.length() / 1e6
        var fell: String? = null
        var s: OrtSession? = null
        if (wantNpu) {
            try {
                s = createNpuSession(context, file)
            } catch (e: Throwable) { // QNN missing/unsupported ops/compile failure: keep the app usable on CPU
                fell = (e.message ?: e.javaClass.simpleName).take(160)
            }
        }
        session = s ?: createCpuSession(file)
        npu = s != null
        npuFallback = fell
        // Debug Part 1: read the declared shapes first; a graph that is not a pose model fails here with a clear sentence, not with ORT_INVALID_ARGUMENT
        Diag.contract(appCtx, modelName, session, expectPose = true)?.let { session.close(); throw IllegalArgumentException(it) }
        if (wantNpu && fell != null) Diag.note(appCtx, "pose", "NPU_FALLBACK", "$modelName runs on CPU: $fell", com.takipli.oynat.core.Sev.WARN)
        inputName = session.inputNames.first()
        val shape = (session.inputInfo.getValue(inputName).info as TensorInfo).shape // [1,3,H,W]
        inputH = shape.getOrNull(2)?.takeIf { it > 0 }?.toInt() ?: 640
        inputW = shape.getOrNull(3)?.takeIf { it > 0 }?.toInt() ?: 640
        chw = FloatArray(3 * inputH * inputW)
        loadMs = (System.nanoTime() - t0) / 1_000_000
        Diag.note(appCtx, "pose", "MODEL_LOADED", "$modelName $provider ${modelMb.toInt()} MB in $loadMs ms | ${Diag.vitals(appCtx)}")
    }

    val provider: String get() = if (npu) "NPU QNN-HTP v75 fp16" else "CPU x$threads"

    private fun createCpuSession(file: File): OrtSession = Qnn.cpuSession(env, file, threads)

    /** QNN HTP (v75) through the shared [Qnn] helper; throws when the graph cannot run there (caller falls back to CPU). */
    private fun createNpuSession(context: Context, file: File): OrtSession = Qnn.npuSession(context, env, file, modelName, threads)

    /** `bmp` must be a software bitmap (not HARDWARE). */
    fun detect(bmp: Bitmap, conf: Double = 0.25, iou: Double = 0.45): PoseResult {
        val t0 = System.nanoTime()
        val layout = letterboxLayout(bmp.width, bmp.height, inputH, inputW)
        val scaled = if (bmp.width == layout.newW && bmp.height == layout.newH) bmp
        else Bitmap.createScaledBitmap(bmp, layout.newW, layout.newH, true)
        val n = layout.newW * layout.newH
        if (argb.size != n) argb = IntArray(n)
        scaled.getPixels(argb, 0, layout.newW, 0, 0, layout.newW, layout.newH)
        if (scaled !== bmp) scaled.recycle()
        preprocessChw(argb, layout, inputH, inputW, chw)
        val t1 = System.nanoTime()

        val (raw, dim0, dim1) = OnnxTensor.createTensor(
            env, FloatBuffer.wrap(chw), longArrayOf(1, 3, inputH.toLong(), inputW.toLong()),
        ).use { input ->
            session.run(mapOf(inputName to input)).use { res ->
                val out = res.get(0) as OnnxTensor
                val shape = out.info.shape // [1,56,N] or [1,N,56]
                val fb = out.floatBuffer
                Triple(FloatArray(fb.remaining()).also { fb.get(it) }, shape[1].toInt(), shape[2].toInt())
            }
        }
        val t2 = System.nanoTime()
        val poses = decodeYoloPose(raw, dim0, dim1, layout.info, bmp.width, bmp.height, conf, iou)
        val t3 = System.nanoTime()
        return PoseResult(poses, (t1 - t0) / 1e6, (t2 - t1) / 1e6, (t3 - t2) / 1e6)
    }

    /** Rotation-robust detection: lets the model see people who are sideways / upside-down in the frame (lying, flipping, rotated clips). */
    var autoRotate = true
    private var prefRot = 0 // clockwise quarter turns that worked last (0..3), tried first
    private var missStreak = 0
    private var frameNo = 0

    private fun confidentKpts(p: Pose): Int { var n = 0; for (k in 0 until p.count) if (p.conf(k) >= KP_OK) n++; return n }
    private fun weak(ps: List<Pose>) = ps.isEmpty() || ps.maxOf { confidentKpts(it) } < MIN_KPTS
    private fun quality(ps: List<Pose>) = ps.maxOfOrNull { it.score * confidentKpts(it) } ?: 0.0

    /** [detect] on the frame turned `k` x 90 degrees clockwise; poses are mapped back to the original frame. */
    private fun detectRot(bmp: Bitmap, k: Int, conf: Double, iou: Double): PoseResult {
        if (k == 0) return detect(bmp, conf, iou)
        val rot = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, Matrix().apply { postRotate(90f * k) }, true)
        try {
            val r = detect(rot, conf, iou)
            return PoseResult(r.poses.map { unrotate(it, k, bmp.width, bmp.height) }, r.preMs, r.inferMs, r.postMs)
        } finally { if (rot !== bmp) rot.recycle() }
    }

    private fun unrotate(p: Pose, k: Int, ow: Int, oh: Int): Pose {
        fun mx(x: Double, y: Double) = when (k) { 1 -> y; 2 -> ow - x; else -> ow - y }
        fun my(x: Double, y: Double) = when (k) { 1 -> oh - x; 2 -> oh - y; else -> x }
        val ax = mx(p.bbox.x1, p.bbox.y1); val ay = my(p.bbox.x1, p.bbox.y1)
        val bx = mx(p.bbox.x2, p.bbox.y2); val by = my(p.bbox.x2, p.bbox.y2)
        val kp = DoubleArray(p.kpts.size)
        for (i in 0 until p.count) { kp[3 * i] = mx(p.x(i), p.y(i)); kp[3 * i + 1] = my(p.x(i), p.y(i)); kp[3 * i + 2] = p.conf(i) }
        return Pose(BBox(minOf(ax, bx), minOf(ay, by), maxOf(ax, bx), maxOf(ay, by)), p.score, kp)
    }

    /**
     * The last working rotation first; only when that finds nobody (or only junk poses) the other three are tried and the
     * winner is remembered, so a clip that is sideways throughout costs 1 inference per frame after the first one.
     * Poses from the other rotations must be confident (no ghosts); all are merged with NMS.
     */
    fun detectRobust(bmp: Bitmap, conf: Double = 0.25, iou: Double = 0.45): PoseResult {
        if (!autoRotate) return detect(bmp, conf, iou)
        frameNo++
        val first = detectRot(bmp, prefRot, conf, iou)
        if (!weak(first.poses)) { missStreak = 0; return first }
        if (missStreak >= 3 && frameNo % 5 != 0) { missStreak++; return first } // nobody anywhere: do not pay 4x on every frame
        var pre = first.preMs; var inf = first.inferMs; var post = first.postMs
        val all = ArrayList<Pose>(first.poses)
        var bestRot = prefRot; var bestQ = quality(first.poses)
        for (k in 0..3) {
            if (k == prefRot) continue
            val r = detectRot(bmp, k, conf, iou)
            pre += r.preMs; inf += r.inferMs; post += r.postMs
            val good = r.poses.filter { confidentKpts(it) >= MIN_KPTS }
            all += good
            val q = quality(good)
            if (q > bestQ) { bestQ = q; bestRot = k }
        }
        if (bestRot != prefRot) {
            Diag.note(appCtx, "pose", "ROT_PREF", "people found at ${bestRot * 90} deg clockwise (was ${prefRot * 90}), quality ${"%.1f".format(java.util.Locale.ROOT, bestQ)}")
            prefRot = bestRot
        }
        val keep = if (all.size <= 1) all else nms(all.map { it.bbox }, DoubleArray(all.size) { all[it].score }, iou).map { all[it] }
        if (weak(keep)) missStreak++ else missStreak = 0
        return PoseResult(keep, pre, inf, post)
    }

    /** Full pipeline (resize + preprocess + inference + decode) `runs` times after `warmup` unmeasured runs. */
    suspend fun bench(
        bmp: Bitmap,
        runs: Int = 50,
        warmup: Int = 3,
        onProgress: (Int) -> Unit = {},
    ): BenchReport = withContext(Dispatchers.Default) {
        val warmMs = ArrayList<Double>(warmup)
        repeat(warmup) { ensureActive(); warmMs.add(detect(bmp).totalMs) }
        val all = ArrayList<Double>(runs)
        val pre = ArrayList<Double>(runs)
        val inf = ArrayList<Double>(runs)
        val post = ArrayList<Double>(runs)
        var last = 0
        for (i in 1..runs) {
            ensureActive()
            val r = detect(bmp)
            all.add(r.totalMs); pre.add(r.preMs); inf.add(r.inferMs); post.add(r.postMs)
            last = r.poses.size
            onProgress(i)
        }
        val rep = BenchReport(benchStats(all), benchStats(pre), benchStats(inf), benchStats(post), last)
        Diag.bench(appCtx, "pose $modelName $provider", rep.total, warmMs)
        rep
    }

    override fun close() {
        session.close()
    }
}
