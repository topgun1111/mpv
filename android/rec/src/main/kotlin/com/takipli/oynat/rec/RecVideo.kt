package com.takipli.oynat.rec

import android.content.Context
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.net.Uri
import androidx.media3.common.MimeTypes
import kotlin.math.ceil
import com.takipli.oynat.core.displaySize
import com.takipli.oynat.core.normalizeRotation

/** Video track facts. `width`/`height` are the display size with the file rotation AND the manual turn applied; `durationS` 0 = unknown. */
data class VideoInfo(
    val codedW: Int,
    val codedH: Int,
    val rotation: Int,
    val durationS: Double,
    val frameRate: Double?,
    /** Source video bitrate (bit/s): track metadata or measured video samples; null = unknown. */
    val bitrate: Int? = null,
    /** Manual clockwise turn (0/90/180/270) chosen with the rotate buttons, on top of the file's rotation metadata. */
    val userRot: Int = 0,
    val hdr: Boolean = false,
    val hevc: Boolean = false,
    val frameCount: Int? = null,
) {
    val width: Int get() = displaySize(codedW, codedH, rotation + userRot).first
    val height: Int get() = displaySize(codedW, codedH, rotation + userRot).second
}

/** Manual clockwise turn per video (keyed by the uri string), remembered between sessions. */
object RecRot {
    private fun prefs(ctx: Context) = ctx.applicationContext.getSharedPreferences("recrot", Context.MODE_PRIVATE)
    fun get(ctx: Context, key: String): Int = normalizeRotation(prefs(ctx).getInt(key, 0))
    fun set(ctx: Context, key: String, deg: Int) { prefs(ctx).edit().putInt(key, normalizeRotation(deg)).apply() }
}

object RecVideo {
    private fun sourceBitrate(extractor: MediaExtractor, track: Int, format: MediaFormat, durationS: Double): Int? {
        if (format.containsKey(MediaFormat.KEY_BIT_RATE)) {
            format.getInteger(MediaFormat.KEY_BIT_RATE).takeIf { it > 0 }?.let { return it }
        }
        if (durationS <= 0.0) return null
        extractor.selectTrack(track)
        var bytes = 0L
        while (true) {
            val size = extractor.sampleSize
            if (size < 0) break
            bytes += size
            if (!extractor.advance()) break
        }
        if (bytes <= 0) return null
        return ceil(bytes * 8.0 / durationS).coerceAtMost(Int.MAX_VALUE.toDouble()).toInt()
    }

    private fun sourceFrameCount(ctx: Context, uri: Uri): Int? = runCatching {
        MediaMetadataRetriever().use { retriever ->
            retriever.setDataSource(ctx, uri)
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_FRAME_COUNT)
                ?.toIntOrNull()?.takeIf { it > 0 }
        }
    }.getOrNull()

    /** Reads the first video track (content:// or file). Blocking: call from Dispatchers.IO. */
    fun probe(ctx: Context, uri: Uri): VideoInfo {
        val ex = MediaExtractor()
        try {
            ex.setDataSource(ctx, uri, null)
            for (i in 0 until ex.trackCount) {
                val f = ex.getTrackFormat(i)
                val mime = f.getString(MediaFormat.KEY_MIME)
                if (mime?.startsWith("video/") != true) continue
                val durationS = if (f.containsKey(MediaFormat.KEY_DURATION)) f.getLong(MediaFormat.KEY_DURATION) / 1e6 else 0.0
                return VideoInfo(
                    codedW = f.getInteger(MediaFormat.KEY_WIDTH),
                    codedH = f.getInteger(MediaFormat.KEY_HEIGHT),
                    rotation = normalizeRotation(if (f.containsKey(MediaFormat.KEY_ROTATION)) f.getInteger(MediaFormat.KEY_ROTATION) else 0),
                    durationS = durationS,
                    frameRate = if (f.containsKey(MediaFormat.KEY_FRAME_RATE)) f.getInteger(MediaFormat.KEY_FRAME_RATE).toDouble() else null,
                    bitrate = sourceBitrate(ex, i, f, durationS),
                    hevc = mime == MimeTypes.VIDEO_H265,
                    frameCount = sourceFrameCount(ctx, uri),
                    userRot = RecRot.get(ctx, uri.toString()),
                    hdr = f.containsKey(MediaFormat.KEY_COLOR_TRANSFER) &&
                        f.getInteger(MediaFormat.KEY_COLOR_TRANSFER) in setOf(
                            MediaFormat.COLOR_TRANSFER_ST2084, MediaFormat.COLOR_TRANSFER_HLG,
                        ),
                )
            }
        } finally {
            ex.release()
        }
        throw IllegalArgumentException("no video track")
    }
}
