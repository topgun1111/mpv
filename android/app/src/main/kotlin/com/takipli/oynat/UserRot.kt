package com.takipli.oynat

import android.content.Context
import com.takipli.oynat.core.normalizeRotation

/**
 * Manual clockwise rotation (0/90/180/270) the user chose for a video, on top of the file's rotation metadata. Keyed by the video uri string
 * (= `doc.video.path`), so the decoder (scan, pick frame, stabilization), the preview player and the export all read the same value.
 */
object UserRot {
    private fun prefs(ctx: Context) = ctx.applicationContext.getSharedPreferences("userrot", Context.MODE_PRIVATE)
    fun get(ctx: Context, key: String): Int = normalizeRotation(prefs(ctx).getInt(key, 0))
    fun set(ctx: Context, key: String, deg: Int) { prefs(ctx).edit().putInt(key, normalizeRotation(deg)).apply() }
}
