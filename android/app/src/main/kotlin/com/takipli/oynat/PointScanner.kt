package com.takipli.oynat

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import com.takipli.oynat.core.FreePick
import com.takipli.oynat.core.PointTrack
import com.takipli.oynat.core.TrackDoc
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.math.abs

/**
 * Part 16b: second scan for a free-point target. Decode once at the scan's sample grid into a gray frame file (640 px long
 * side), then run [PointTracker] passes A and B over it, and return the observations for `TrackDoc.pt`.
 * `onProgress(done, total, t)`: first `n` steps decode, then the 4 tracker steps.
 */
object PointScanner {
    /** Delete decoded-frame caches (call when a new video/scan starts). */
    fun clearCache(ctx: Context) { ctx.cacheDir.listFiles { f -> f.name.startsWith("pt-") }?.forEach { it.delete() } }

    private const val SIDE = 640

    suspend fun run(ctx: Context, uri: Uri, doc: TrackDoc, pick: FreePick, onProgress: (Int, Int, Double) -> Unit = { _, _, _ -> }): PointTrack =
        withContext(Dispatchers.Default) {
            check(OpenCvFlow.available) { "OpenCV not available" }
            val n = doc.samples.size
            require(n > 0) { "empty scan" }
            val vw = doc.video.w.coerceAtLeast(1); val vh = doc.video.h.coerceAtLeast(1)
            val sc = SIDE.toDouble() / maxOf(vw, vh)
            val gw = (vw * sc).toInt().coerceAtLeast(64) and 1.inv(); val gh = (vh * sc).toInt().coerceAtLeast(64) and 1.inv()
            val fps = doc.sampleFps.takeIf { it > 0 } ?: 10.0
            val file = File(ctx.cacheDir, "pt-${(doc.video.path + n + gw).hashCode()}.gray") // kept: manual re-tracks reuse the decoded frames
            val ts = doc.samples.map { it.t }
            val job = currentCoroutineContext()[kotlinx.coroutines.Job]
            fun nearest(t: Double): Int {
                var lo = 0; var hi = n - 1
                while (hi - lo > 1) { val m = (lo + hi) / 2; if (ts[m] <= t) lo = m else hi = m }
                return if (abs(ts[lo] - t) <= abs(ts[hi] - t)) lo else hi
            }
            try {
                GrayStore(file, gw, gh, n, resume = true).use { store ->
                    if (!store.complete) VideoDecoder.sample(ctx, uri, fps, 0.0, maxSide = 960) { f ->
                        currentCoroutineContext().ensureActive()
                        val i = nearest(f.t)
                        if (abs(ts[i] - f.t) <= 0.6 / fps && !store.has(i)) {
                            val small = Bitmap.createScaledBitmap(f.bitmap, gw, gh, true)
                            val px = IntArray(gw * gh); small.getPixels(px, 0, gw, 0, 0, gw, gh)
                            if (small !== f.bitmap) small.recycle()
                            store.put(i, ByteArray(gw * gh) { k -> val p = px[k]; ((((p shr 16) and 255) * 77 + ((p shr 8) and 255) * 150 + (p and 255) * 29) shr 8).toByte() })
                            onProgress(i, n + pick.pins.size + 4, f.t)
                        }
                        f.bitmap.recycle()
                        true
                    }
                    store.saveIndex()
                    val seeds = pick.pins.filter { it.size >= 3 }.map { Triple(nearest(it[0]), it[1], it[2]) } + Triple(nearest(pick.t), pick.x, pick.y) // pins first: they win a tie
                    val pi = nearest(pick.t)
                    val tracker = PointTracker(store, doc.samples.map { it.cam })
                    val (a, b) = tracker.multiPass(seeds, { s -> onProgress(n + s, n + seeds.size + 3, ts[pi]) }) { job?.ensureActive() }
                    PointTrack(a, b)
                }
            } catch (e: Throwable) { file.delete(); File(file.path + ".has").delete(); throw e }
        }
}
