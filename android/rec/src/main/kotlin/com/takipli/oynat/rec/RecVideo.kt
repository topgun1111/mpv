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
    /** Reads the first video track (content:// or file). Blocking: call from Dispatchers.IO. */
    fun probe(ctx: Context, uri: Uri): VideoInfo {
        val ex = MediaExtractor()
        try {
            ex.setDataSource(ctx, uri, null)
            for (i in 0 until ex.trackCount) {
                val f = ex.getTrackFormat(i)
                if (f.getString(MediaFormat.KEY_MIME)?.startsWith("video/") != true) continue
                return VideoInfo(
                    codedW = f.getInteger(MediaFormat.KEY_WIDTH),
                    codedH = f.getInteger(MediaFormat.KEY_HEIGHT),
                    rotation = normalizeRotation(if (f.containsKey(MediaFormat.KEY_ROTATION)) f.getInteger(MediaFormat.KEY_ROTATION) else 0),
                    durationS = if (f.containsKey(MediaFormat.KEY_DURATION)) f.getLong(MediaFormat.KEY_DURATION) / 1e6 else 0.0,
                    frameRate = if (f.containsKey(MediaFormat.KEY_FRAME_RATE)) f.getInteger(MediaFormat.KEY_FRAME_RATE).toDouble() else null,
                    userRot = RecRot.get(ctx, uri.toString()),
                )
            }
        } finally {
            ex.release()
        }
        throw IllegalArgumentException("no video track")
    }
}
