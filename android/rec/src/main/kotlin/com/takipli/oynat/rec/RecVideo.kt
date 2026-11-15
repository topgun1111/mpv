package com.takipli.oynat.rec

import android.content.Context
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import com.takipli.oynat.core.displaySize
import com.takipli.oynat.core.normalizeRotation

/** Video track facts. `width`/`height` are the display size with the file rotation AND the manual turn applied; `durationS` 0 = unknown. */
data class VideoInfo(
    val codedW: Int,
    val codedH: Int,
    val rotation: Int,
    val durationS: Double,
    val frameRate: Double?,
    /** Source video bitrate (bit/s): the track's own value, else file size / duration; null = unknown (the export then uses a formula). */
    val bitrate: Int? = null,
    /** Manual clockwise turn (0/90/180/270) chosen with the rotate buttons, on top of the file's rotation metadata. */
    val userRot: Int = 0,
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
    /** The track's KEY_BIT_RATE; if the container does not carry it, the whole file's size / duration (a little high: it includes audio). */
    private fun sourceBitrate(ctx: Context, uri: Uri, f: MediaFormat, durationS: Double): Int? {
        if (f.containsKey(MediaFormat.KEY_BIT_RATE)) f.getInteger(MediaFormat.KEY_BIT_RATE).takeIf { it > 0 }?.let { return it }
        if (durationS <= 0.0) return null
        val bytes = runCatching { ctx.contentResolver.openFileDescriptor(uri, "r")?.use { it.statSize } }.getOrNull() ?: return null
        if (bytes <= 0L) return null
        return (bytes * 8.0 / durationS).coerceAtMost(Int.MAX_VALUE.toDouble()).toInt()
    }

    /** Reads the first video track (content:// or file). Blocking: call from Dispatchers.IO. */
    fun probe(ctx: Context, uri: Uri): VideoInfo {
        val ex = MediaExtractor()
        try {
            ex.setDataSource(ctx, uri, null)
            for (i in 0 until ex.trackCount) {
                val f = ex.getTrackFormat(i)
                if (f.getString(MediaFormat.KEY_MIME)?.startsWith("video/") != true) continue
                val durationS = if (f.containsKey(MediaFormat.KEY_DURATION)) f.getLong(MediaFormat.KEY_DURATION) / 1e6 else 0.0
                return VideoInfo(
                    codedW = f.getInteger(MediaFormat.KEY_WIDTH),
                    codedH = f.getInteger(MediaFormat.KEY_HEIGHT),
                    rotation = normalizeRotation(if (f.containsKey(MediaFormat.KEY_ROTATION)) f.getInteger(MediaFormat.KEY_ROTATION) else 0),
                    durationS = durationS,
                    frameRate = if (f.containsKey(MediaFormat.KEY_FRAME_RATE)) f.getInteger(MediaFormat.KEY_FRAME_RATE).toDouble() else null,
                    bitrate = sourceBitrate(ctx, uri, f, durationS),
                    userRot = RecRot.get(ctx, uri.toString()),
                )
            }
        } finally {
            ex.release()
        }
        throw IllegalArgumentException("no video track")
    }
}
