package com.takipli.oynat

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import com.takipli.oynat.core.FreePick
import com.takipli.oynat.core.PointTrack
import com.takipli.oynat.core.combineDots
import com.takipli.oynat.core.TrackDoc
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import kotlin.math.abs

/**
 * Part 16b: second scan for a free-point target. Decode once at the scan's sample grid into a gray frame file (640 px long
 * side), then run [PointTracker] passes A and B over it, and return the observations for `TrackDoc.pt`.
 * `onProgress(done, total, t)`: first `n` steps decode, then the 4 tracker steps.
 */
object PointScanner {
    private const val SIDE = 640
    /** Bound the optional SAM pass; use the optical-flow fallback when it cannot finish in time. */
    private const val SAM_BUDGET_MS = 5 * 60 * 1000L

    suspend fun run(ctx: Context, uri: Uri, doc: TrackDoc, pick: FreePick, allowSam: Boolean = true,
                    onProgress: (Int, Int, Double, ScanStage) -> Unit = { _, _, _, _ -> }): PointTrack =
        withContext(Dispatchers.Default) {
            // `sam` build: SAM 2 first (accuracy over speed); any failure falls back to the optical-flow tracker below.
            // (The `pose` build's SamEngine always returns null.)
            if (allowSam && SamEngine.hasModels(ctx)) {
                try {
                    val sam = withTimeoutOrNull(SAM_BUDGET_MS) {
                        SamEngine.track(ctx, uri, doc, pick) { done, total, t ->
                            onProgress(done, total, t, if (done <= (total - 1) / 2) ScanStage.POINT_DECODE else ScanStage.POINT_TRACK)
                        }
                    }
                    if (sam != null) return@withContext sam
                    Diag.note(ctx, "point", "SAM_FALLBACK", "SAM returned no track or exceeded ${SAM_BUDGET_MS / 1000}s: trying optical flow", com.takipli.oynat.core.Sev.WARN)
                }
                catch (e: kotlinx.coroutines.CancellationException) { throw e }
                catch (e: Throwable) { ErrorLog.record(ctx, "sam", e) }
            }
            check(OpenCvFlow.available) { "OpenCV not available" }
            val n = doc.samples.size
            require(n > 0) { "empty scan" }
            val vw = doc.video.w.coerceAtLeast(1); val vh = doc.video.h.coerceAtLeast(1)
            val sc = SIDE.toDouble() / maxOf(vw, vh)
            val gw = (vw * sc).toInt().coerceAtLeast(64) and 1.inv(); val gh = (vh * sc).toInt().coerceAtLeast(64) and 1.inv()
            val fps = doc.sampleFps.takeIf { it > 0 } ?: 10.0
            val file = File(ctx.cacheDir, "pt-${System.nanoTime()}.gray")
            val ts = doc.samples.map { it.t }
            val job = currentCoroutineContext()[kotlinx.coroutines.Job]
            fun nearest(t: Double): Int {
                var lo = 0; var hi = n - 1
                while (hi - lo > 1) { val m = (lo + hi) / 2; if (ts[m] <= t) lo = m else hi = m }
                return if (abs(ts[lo] - t) <= abs(ts[hi] - t)) lo else hi
            }
            try {
                GrayStore(file, gw, gh, n).use { store ->
                    VideoDecoder.sample(ctx, uri, fps, 0.0, maxSide = 960, userRot = UserRot.forDoc(ctx, doc)) { f ->
                        currentCoroutineContext().ensureActive()
                        if (f.t > ts[n - 1] + 0.6 / fps) { f.bitmap.recycle(); return@sample false } // partial doc (cancelled scan): nothing to decode past the last sample
                        val i = nearest(f.t)
                        if (abs(ts[i] - f.t) <= 0.6 / fps && !store.has(i)) {
                            val small = Bitmap.createScaledBitmap(f.bitmap, gw, gh, true)
                            val px = IntArray(gw * gh); small.getPixels(px, 0, gw, 0, 0, gw, gh)
                            if (small !== f.bitmap) small.recycle()
                            store.put(i, ByteArray(gw * gh) { k -> val p = px[k]; ((((p shr 16) and 255) * 77 + ((p shr 8) and 255) * 150 + (p and 255) * 29) shr 8).toByte() })
                            onProgress(i + 1, n + 4, f.t, ScanStage.POINT_DECODE)
                        }
                        f.bitmap.recycle()
                        true
                    }
                    val seeds = listOf(Triple(nearest(pick.t), pick.x, pick.y))
                    val pi = nearest(pick.t)
                    val cams = doc.samples.map { it.cam }
                    val (a, b) = if (pick.dots.size >= 2) { // several dots on one limb: each is tracked like a single point, then combined
                        val m = pick.dots.size
                        val per = pick.dots.mapIndexed { k, d ->
                            PointTracker(store, cams).multiPass(listOf(Triple(pi, d[0], d[1])), { s -> onProgress(n + k * 4 + s, n + 4 * m, ts[pi], ScanStage.POINT_TRACK) }) { job?.ensureActive() }
                        }
                        combineDots(per.map { it.first }, pick.dots, n) to combineDots(per.map { it.second }, pick.dots, n)
                    } else if (pick.shapes.isNotEmpty()) { // Part 18: drawn region
                        val polys = pick.shapes.filter { it.size >= 3 }.map { poly -> DoubleArray(poly.size * 2) { i -> if (i % 2 == 0) poly[i / 2][0] * gw else poly[i / 2][1] * gh } }
                        RegionTracker(store, cams).twoPass(pi, polys, { s -> onProgress(n + s, n + 4, ts[pi], ScanStage.POINT_TRACK) }) { job?.ensureActive() }
                    } else PointTracker(store, cams).multiPass(seeds, { s -> onProgress(n + s, n + seeds.size + 3, ts[pi], ScanStage.POINT_TRACK) }) { job?.ensureActive() }
                    PointTrack(a, b)
                }
            } finally { file.delete() }
        }
}
