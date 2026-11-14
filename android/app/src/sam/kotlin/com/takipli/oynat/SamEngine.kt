package com.takipli.oynat

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import com.takipli.oynat.core.FreePick
import com.takipli.oynat.core.PointTrack
import com.takipli.oynat.core.TrackDoc
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.FloatBuffer
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * `sam` build: accuracy-first tracker for free-point / drawn-region targets, using SAM 2.1 (image encoder + prompt decoder).
 * Per sampled frame (SAM_FPS, default 3; slow on purpose): predict the object's box from the last good step (constant
 * velocity, grown while lost), prompt SAM with that box + a positive point inside the previous mask, take the 3 candidate
 * masks and keep the one that agrees best with the prediction (predicted IoU x box overlap x area sanity). Runs forward and
 * backward from the pick, then interpolates to the scan's sample grid. Output rows `[x, y, conf]` = mask centroid, same
 * format as `PointTracker`, so views building is unchanged. This is track-by-prompting, not SAM 2's memory tracker.
 */
object SamEngine {
    private const val ENC = "sam2-encoder.onnx"
    private const val DEC = "sam2-decoder.onnx"
    private const val SAM_FPS = 3.0
    private const val S = 1024          // SAM input side (frame is resized to S x S, aspect ignored, like SAM 2)
    private const val M = 256           // mask logits side
    private const val MIN_CONF = 0.35
    private const val MAX_GAP_S = 1.0   // interpolation across a lost span only up to this long
    private val MEAN = floatArrayOf(0.485f, 0.456f, 0.406f)
    private val STD = floatArrayOf(0.229f, 0.224f, 0.225f)

    fun hasModels(ctx: Context): Boolean = ModelStore.list(ctx).let { ENC in it && DEC in it }

    private class Box(val x1: Double, val y1: Double, val x2: Double, val y2: Double) { // normalized
        val cx get() = (x1 + x2) / 2
        val cy get() = (y1 + y2) / 2
        val w get() = x2 - x1
        val h get() = y2 - y1
        fun grow(f: Double, minSide: Double = 0.03): Box {
            val nw = max(w * f, minSide); val nh = max(h * f, minSide)
            return Box((cx - nw / 2).coerceIn(0.0, 1.0), (cy - nh / 2).coerceIn(0.0, 1.0), (cx + nw / 2).coerceIn(0.0, 1.0), (cy + nh / 2).coerceIn(0.0, 1.0))
        }
        fun shift(dx: Double, dy: Double) = Box((x1 + dx).coerceIn(0.0, 1.0), (y1 + dy).coerceIn(0.0, 1.0), (x2 + dx).coerceIn(0.0, 1.0), (y2 + dy).coerceIn(0.0, 1.0))
        fun iou(o: Box): Double {
            val iw = max(0.0, min(x2, o.x2) - max(x1, o.x1)); val ih = max(0.0, min(y2, o.y2) - max(y1, o.y1))
            val i = iw * ih; val u = w * h + o.w * o.h - i
            return if (u > 0) i / u else 0.0
        }
    }

    private class Cand(val box: Box, val cx: Double, val cy: Double, val area: Double, val iouPred: Double, val inPx: Int, val inPy: Int)

    private class Session(val env: OrtEnvironment, val enc: OrtSession, val dec: OrtSession) : AutoCloseable {
        override fun close() { enc.close(); dec.close() }
    }

    private fun open(ctx: Context): Session {
        val env = OrtEnvironment.getEnvironment()
        fun mk(name: String) = OrtSession.SessionOptions().use { o ->
            o.setIntraOpNumThreads(4); o.setInterOpNumThreads(1)
            o.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
            env.createSession(ModelStore.materialize(ctx, name).absolutePath, o)
        }
        return Session(env, mk(ENC), mk(DEC))
    }

    private fun chw(bmp: Bitmap): FloatArray {
        val sb = if (bmp.width == S && bmp.height == S) bmp else Bitmap.createScaledBitmap(bmp, S, S, true)
        val px = IntArray(S * S); sb.getPixels(px, 0, S, 0, 0, S, S)
        if (sb !== bmp) sb.recycle()
        val out = FloatArray(3 * S * S)
        for (i in px.indices) {
            val p = px[i]
            out[i] = (((p shr 16) and 255) / 255f - MEAN[0]) / STD[0]
            out[S * S + i] = (((p shr 8) and 255) / 255f - MEAN[1]) / STD[1]
            out[2 * S * S + i] = ((p and 255) / 255f - MEAN[2]) / STD[2]
        }
        return out
    }

    /** Runs the encoder for one frame and the decoder for one prompt; calls `use` with the 3 candidates. */
    private fun segment(s: Session, image: FloatArray, coords: FloatArray, labels: FloatArray): List<Cand> {
        val n = labels.size
        val inputs = HashMap<String, OnnxTensor>()
        try {
            OnnxTensor.createTensor(s.env, FloatBuffer.wrap(image), longArrayOf(1, 3, S.toLong(), S.toLong())).use { img ->
                s.enc.run(mapOf(s.enc.inputNames.first() to img)).use { er ->
                    inputs["image_embed"] = er.get("image_embed").get() as OnnxTensor
                    inputs["high_res_feats_0"] = er.get("high_res_feats_0").get() as OnnxTensor
                    inputs["high_res_feats_1"] = er.get("high_res_feats_1").get() as OnnxTensor
                    inputs["point_coords"] = OnnxTensor.createTensor(s.env, FloatBuffer.wrap(coords), longArrayOf(1, n.toLong(), 2))
                    inputs["point_labels"] = OnnxTensor.createTensor(s.env, FloatBuffer.wrap(labels), longArrayOf(1, n.toLong()))
                    inputs["mask_input"] = OnnxTensor.createTensor(s.env, FloatBuffer.wrap(FloatArray(M * M)), longArrayOf(1, 1, M.toLong(), M.toLong()))
                    inputs["has_mask_input"] = OnnxTensor.createTensor(s.env, FloatBuffer.wrap(floatArrayOf(0f)), longArrayOf(1))
                    s.dec.run(inputs).use { dr ->
                        val m = dr.get("low_res_masks").get() as OnnxTensor
                        val q = dr.get("iou_predictions").get() as OnnxTensor
                        val mb = m.floatBuffer; val qb = q.floatBuffer
                        val masks = FloatArray(mb.remaining()).also { mb.get(it) }
                        val iou = FloatArray(qb.remaining()).also { qb.get(it) }
                        return (0 until iou.size).map { k -> analyse(masks, k, iou[k].toDouble()) }
                    }
                }
            }
        } finally {
            for (k in listOf("point_coords", "point_labels", "mask_input", "has_mask_input")) inputs[k]?.close()
        }
    }

    private fun analyse(masks: FloatArray, k: Int, iouPred: Double): Cand {
        val o = k * M * M
        var n = 0; var sx = 0.0; var sy = 0.0; var x1 = M; var y1 = M; var x2 = -1; var y2 = -1
        var ix = -1; var iy = -1; var best = 0f
        for (y in 0 until M) for (x in 0 until M) {
            val v = masks[o + y * M + x]
            if (v > 0f) {
                n++; sx += x; sy += y
                if (x < x1) x1 = x; if (x > x2) x2 = x; if (y < y1) y1 = y; if (y > y2) y2 = y
                if (v > best) { best = v; ix = x; iy = y }
            }
        }
        if (n == 0) return Cand(Box(0.0, 0.0, 0.0, 0.0), 0.0, 0.0, 0.0, iouPred, -1, -1)
        return Cand(Box(x1.toDouble() / M, y1.toDouble() / M, (x2 + 1).toDouble() / M, (y2 + 1).toDouble() / M),
            sx / n / M, sy / n / M, n.toDouble() / (M * M), iouPred, ix, iy)
    }

    private fun prompt(box: Box?, px: Double, py: Double): Pair<FloatArray, FloatArray> {
        val c = ArrayList<Float>(); val l = ArrayList<Float>()
        if (box != null) {
            c += (box.x1 * S).toFloat(); c += (box.y1 * S).toFloat(); l += 2f
            c += (box.x2 * S).toFloat(); c += (box.y2 * S).toFloat(); l += 3f
        }
        c += (px * S).toFloat(); c += (py * S).toFloat(); l += 1f
        return c.toFloatArray() to l.toFloatArray()
    }

    private class Step(val cx: Double, val cy: Double, val conf: Double)

    /** Walks `order` (frame indices, pick frame first) from the pick; returns per-frame result (null = lost). */
    private suspend fun walk(s: Session, files: List<File>, order: List<Int>, pick: FreePick, onFrame: () -> Unit): Map<Int, Step> {
        val res = HashMap<Int, Step>()
        var box: Box? = null; var area = 0.0; var vx = 0.0; var vy = 0.0; var lastCx = 0.0; var lastCy = 0.0
        var px = pick.x; var py = pick.y; var lost = 0
        val region = pick.shapes.filter { it.size >= 3 }.flatten()
        for ((step, fi) in order.withIndex()) {
            currentCoroutineContext().ensureActive()
            val bmp = BitmapFactory.decodeFile(files[fi].path) ?: continue
            val img = try { chw(bmp) } finally { bmp.recycle() }
            if (step == 0) {
                val seed: Box? = if (region.isNotEmpty()) Box(region.minOf { it[0] }, region.minOf { it[1] }, region.maxOf { it[0] }, region.maxOf { it[1] }) else null
                val (c, l) = prompt(seed, if (seed != null) seed.cx else pick.x, if (seed != null) seed.cy else pick.y)
                val cands = segment(s, img, c, l).filter { it.area > 0 }
                if (cands.isEmpty()) return res
                val top = cands.maxOf { it.iouPred }
                // several valid masks (part vs whole): the smallest one that is almost as confident as the best = the tapped detail
                val pickC = cands.filter { it.iouPred >= 0.85 * top }.minByOrNull { it.area }!!
                box = pickC.box; area = pickC.area; lastCx = pickC.cx; lastCy = pickC.cy
                px = pickC.inPx.toDouble() / M; py = pickC.inPy.toDouble() / M
                res[fi] = Step(pickC.cx, pickC.cy, pickC.iouPred)
            } else {
                val b0 = box!!
                val pred = b0.shift(vx, vy).grow(1.2 + 0.3 * lost.coerceAtMost(4))
                val (c, l) = prompt(pred, px, py)
                val cands = segment(s, img, c, l).filter { it.area > 0 }
                val ratio = { a: Double -> if (area > 0) a / area else 1.0 }
                val best = cands.map { cd ->
                    val ov = cd.box.iou(pred)
                    val sane = if (ratio(cd.area) in 0.4..2.5) 1.0 else 0.5
                    cd to cd.iouPred * sqrt(ov) * sane
                }.maxByOrNull { it.second }
                val conf = best?.second ?: 0.0
                if (best != null && conf >= MIN_CONF) {
                    val cd = best.first
                    vx = (cd.cx - lastCx).coerceIn(-b0.w, b0.w); vy = (cd.cy - lastCy).coerceIn(-b0.h, b0.h)
                    lastCx = cd.cx; lastCy = cd.cy; box = cd.box; area = 0.7 * area + 0.3 * cd.area
                    px = cd.inPx.toDouble() / M; py = cd.inPy.toDouble() / M; lost = 0
                    res[fi] = Step(cd.cx, cd.cy, conf.coerceAtMost(1.0))
                } else { lost++; vx *= 0.7; vy *= 0.7; box = pred.let { Box(it.x1, it.y1, it.x2, it.y2) } }
            }
            onFrame()
        }
        return res
    }

    /** Returns rows aligned to `doc.samples`, or null when SAM cannot run (caller falls back to the optical-flow tracker). */
    suspend fun track(ctx: Context, uri: Uri, doc: TrackDoc, pick: FreePick, onProgress: (Int, Int, Double) -> Unit): PointTrack? =
        withContext(Dispatchers.Default) {
            if (!hasModels(ctx)) return@withContext null
            val dir = File(ctx.cacheDir, "sam-${System.nanoTime()}").also { it.mkdirs() }
            try {
                val files = ArrayList<File>(); val ts = ArrayList<Double>()
                VideoDecoder.sample(ctx, uri, SAM_FPS, 0.0, maxSide = S) { f ->
                    currentCoroutineContext().ensureActive()
                    val file = File(dir, "${files.size}.jpg")
                    file.outputStream().use { f.bitmap.compress(Bitmap.CompressFormat.JPEG, 95, it) }
                    files += file; ts += f.t
                    f.bitmap.recycle()
                    onProgress(files.size, 0, f.t)
                    true
                }
                if (files.size < 2) return@withContext null
                val total = files.size * 2
                var done = files.size
                var p = 0
                for (i in ts.indices) if (abs(ts[i] - pick.t) < abs(ts[p] - pick.t)) p = i
                val steps = HashMap<Int, Step>()
                open(ctx).use { s ->
                    val tick = { done++; onProgress(done, total, ts[(done - files.size - 1).coerceIn(0, ts.size - 1)]) }
                    steps += walk(s, files, (p until files.size).toList(), pick, tick)
                    steps += walk(s, files, (p downTo 0).toList(), pick, tick).filterKeys { it != p }
                }
                if (steps.isEmpty()) return@withContext null
                val keys = steps.keys.sorted()
                val rows = doc.samples.map { smp ->
                    val t = smp.t
                    val hi = keys.firstOrNull { ts[it] >= t }
                    val lo = keys.lastOrNull { ts[it] <= t }
                    when {
                        lo == null || hi == null -> if ((lo ?: hi)?.let { abs(ts[it] - t) <= 0.5 / SAM_FPS } == true) steps[lo ?: hi]!!.let { listOf(it.cx, it.cy, it.conf) } else emptyList()
                        lo == hi -> steps[lo]!!.let { listOf(it.cx, it.cy, it.conf) }
                        ts[hi] - ts[lo] > MAX_GAP_S -> { // inside a long lost span: only the near-edge frames count
                            val near = if (t - ts[lo] <= ts[hi] - t) lo else hi
                            if (abs(ts[near] - t) <= 0.5 / SAM_FPS) steps[near]!!.let { listOf(it.cx, it.cy, it.conf) } else emptyList()
                        }
                        else -> {
                            val a = steps[lo]!!; val b = steps[hi]!!; val u = (t - ts[lo]) / (ts[hi] - ts[lo])
                            listOf(a.cx + (b.cx - a.cx) * u, a.cy + (b.cy - a.cy) * u, min(a.conf, b.conf))
                        }
                    }
                }
                PointTrack(a = rows, b = emptyList())
            } finally { dir.deleteRecursively() }
        }
}
