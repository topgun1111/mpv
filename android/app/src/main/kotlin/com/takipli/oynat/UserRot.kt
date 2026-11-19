package com.takipli.oynat

import android.content.Context
import com.takipli.oynat.core.TrackDoc
import com.takipli.oynat.core.docRotation
import com.takipli.oynat.core.normalizeRotation

/**
 * Manual clockwise rotation (0/90/180/270) the user chose for a video, on top of the file's rotation metadata. Keyed by the video uri string
 * (= `doc.video.path`), so the decoder (scan, pick frame, stabilization), the preview player and the export all read the same value.
 */
object UserRot {
    private fun prefs(ctx: Context) = ctx.applicationContext.getSharedPreferences("userrot", Context.MODE_PRIVATE)
    fun get(ctx: Context, key: String): Int = normalizeRotation(prefs(ctx).getInt(key, 0))
    fun set(ctx: Context, key: String, deg: Int) { prefs(ctx).edit().putInt(key, normalizeRotation(deg)).apply() }

    /**
     * The turn a finished scan was made with (stored in the scan file; the per-video setting only for files that predate it).
     * Everything that works on an existing scan (second-pass trackers, stabilization, preview, export) must use this, not [get]:
     * the user may have rotated the clip again on the pick screen since, and the tracking data is in the old orientation.
     */
    fun forDoc(ctx: Context, doc: TrackDoc): Int = docRotation(doc.video.rot, get(ctx, doc.video.path))
}
