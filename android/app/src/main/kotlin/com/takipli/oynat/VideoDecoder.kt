package com.takipli.oynat

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.media.Image
import android.media.ImageReader
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import android.os.Handler
import android.os.HandlerThread
import com.takipli.oynat.core.SampleSelector
import com.takipli.oynat.core.displaySize
import com.takipli.oynat.core.normalizeRotation
import com.takipli.oynat.core.scaledSize
import com.takipli.oynat.core.yuv709ToArgb
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** Video track facts. `width`/`height` are the display size (rotation applied); `durationS` 0 = unknown. */
data class VideoInfo(
    val codedW: Int,
    val codedH: Int,
    val rotation: Int,
    val durationS: Double,
    val frameRate: Double?,
    val mime: String,
) {
    val width: Int get() = displaySize(codedW, codedH, rotation).first
    val height: Int get() = displaySize(codedW, codedH, rotation).second
}

/** One sampled frame: `t` = the frame's real presentation time (s); `bitmap` upright, longer side <= maxSide. */
class SampledFrame(val t: Double, val bitmap: Bitmap)

object VideoDecoder {
    private fun openExtractor(ctx: Context, uri: Uri): Pair<MediaExtractor, Int> {
        val ex = MediaExtractor()
        try {
            ex.setDataSource(ctx, uri, null) // content:// (Storage Access Framework) or file
            for (i in 0 until ex.trackCount) {
                if (ex.getTrackFormat(i).getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true) return ex to i
            }
        } catch (e: Throwable) {
            ex.release()
            throw e
        }
        ex.release()
        throw IllegalArgumentException("no video track")
    }

    private fun MediaFormat.intOr(key: String, def: Int) = if (containsKey(key)) getInteger(key) else def

    fun probe(ctx: Context, uri: Uri): VideoInfo {
        val (ex, i) = openExtractor(ctx, uri)
        try {
            val f = ex.getTrackFormat(i)
            return VideoInfo(
                codedW = f.getInteger(MediaFormat.KEY_WIDTH),
                codedH = f.getInteger(MediaFormat.KEY_HEIGHT),
                rotation = normalizeRotation(f.intOr(MediaFormat.KEY_ROTATION, 0)),
                durationS = if (f.containsKey(MediaFormat.KEY_DURATION)) f.getLong(MediaFormat.KEY_DURATION) / 1e6 else 0.0,
                frameRate = if (f.containsKey(MediaFormat.KEY_FRAME_RATE)) f.getInteger(MediaFormat.KEY_FRAME_RATE).toDouble() else null,
                mime = f.getString(MediaFormat.KEY_MIME).orEmpty(),
            )
        } finally {
            ex.release()
        }
    }

    /**
     * Decodes in presentation order and hands `onFrame` the frames chosen by [SampleSelector] (grid at `fps`,
     * starting at `startS`, stopping after `endS`). Only chosen frames are rendered/converted, the rest are
     * decoded and dropped. Seeks to the sync frame before `startS`, so resuming mid-video is cheap.
     * `onFrame` returns false to stop. Cancellable. Returns the number of samples delivered.
     */
    suspend fun sample(
        ctx: Context,
        uri: Uri,
        fps: Double,
        startS: Double = 0.0,
        endS: Double = Double.POSITIVE_INFINITY,
        maxSide: Int = 960,
        onFrame: suspend (SampledFrame) -> Boolean,
    ): Int = withContext(Dispatchers.Default) {
        val (ex, track) = openExtractor(ctx, uri)
        val format = ex.getTrackFormat(track)
        val mime = format.getString(MediaFormat.KEY_MIME)!!
        val rotation = normalizeRotation(format.intOr(MediaFormat.KEY_ROTATION, 0))
        val thread = HandlerThread("frame-reader").also { it.start() }
        val queue = LinkedBlockingQueue<Image>()
        val reader = ImageReader.newInstance(
            format.getInteger(MediaFormat.KEY_WIDTH), format.getInteger(MediaFormat.KEY_HEIGHT),
            ImageFormat.YUV_420_888, 4,
        )
        reader.setOnImageAvailableListener({ r -> r.acquireNextImage()?.let { queue.offer(it) } }, Handler(thread.looper))
        val codec = MediaCodec.createDecoderByType(mime)
        var delivered = 0
        try {
            ex.selectTrack(track)
            if (startS > 0.0) ex.seekTo((startS * 1e6).toLong(), MediaExtractor.SEEK_TO_PREVIOUS_SYNC)
            codec.configure(format, reader.surface, null, 0)
            codec.start()
            val sel = SampleSelector(fps, startS, endS)
            val info = MediaCodec.BufferInfo()
            var inputDone = false
            var outputDone = false
            while (!outputDone) {
                ensureActive()
                if (!inputDone) {
                    val ii = codec.dequeueInputBuffer(10_000)
                    if (ii >= 0) {
                        val n = ex.readSampleData(codec.getInputBuffer(ii)!!, 0)
                        if (n < 0) {
                            codec.queueInputBuffer(ii, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inputDone = true
                        } else {
                            codec.queueInputBuffer(ii, 0, n, ex.sampleTime, 0)
                            ex.advance()
                        }
                    }
                }
                val oi = codec.dequeueOutputBuffer(info, 10_000)
                if (oi < 0) continue // try-again / format or buffers changed: nothing to do
                val t = info.presentationTimeUs / 1e6
                val eos = info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                val take = info.size > 0 && sel.accept(t)
                codec.releaseOutputBuffer(oi, take) // render only the frames we keep
                var go = !eos && !(info.size > 0 && sel.isPastEnd(t))
                if (take) {
                    val img = queue.poll(3, TimeUnit.SECONDS) ?: error("decoder delivered no image")
                    val bmp = try { toBitmap(img, rotation, maxSide) } finally { img.close() }
                    delivered++
                    if (!onFrame(SampledFrame(t, bmp))) go = false
                }
                if (!go) outputDone = true
            }
        } finally {
            runCatching { codec.stop() }
            codec.release()
            reader.close()
            queue.forEach { it.close() }
            thread.quitSafely()
            ex.release()
        }
        delivered
    }

    /** YUV_420_888 -> upright ARGB bitmap, nearest-neighbour downscale to `maxSide` (cheap; quality upgrade is a later step). */
    private fun toBitmap(img: Image, rotation: Int, maxSide: Int): Bitmap {
        val crop = img.cropRect
        val cw = crop.width()
        val ch = crop.height()
        val (ow, oh) = scaledSize(cw, ch, maxSide)
        val (yp, up, vp) = img.planes.let { Triple(it[0], it[1], it[2]) }
        val yb = yp.buffer; val ub = up.buffer; val vb = vp.buffer
        val px = IntArray(ow * oh)
        for (oy in 0 until oh) {
            val sy = crop.top + (oy.toLong() * ch / oh).toInt()
            for (ox in 0 until ow) {
                val sx = crop.left + (ox.toLong() * cw / ow).toInt()
                val y = yb.get(sy * yp.rowStride + sx * yp.pixelStride).toInt() and 255
                val u = ub.get((sy shr 1) * up.rowStride + (sx shr 1) * up.pixelStride).toInt() and 255
                val v = vb.get((sy shr 1) * vp.rowStride + (sx shr 1) * vp.pixelStride).toInt() and 255
                px[oy * ow + ox] = yuv709ToArgb(y, u, v)
            }
        }
        val bmp = Bitmap.createBitmap(px, ow, oh, Bitmap.Config.ARGB_8888)
        if (rotation == 0) return bmp
        val m = Matrix().apply { postRotate(rotation.toFloat()) }
        return Bitmap.createBitmap(bmp, 0, 0, ow, oh, m, true).also { bmp.recycle() }
    }
}
