package com.takipli.oynat

import android.content.Context
import android.net.Uri
import com.takipli.oynat.core.FreePick
import com.takipli.oynat.core.PointTrack
import com.takipli.oynat.core.TrackDoc

/** `pose` build: no SAM. The real implementation lives in src/sam (same signatures). */
object SamEngine {
    fun hasModels(ctx: Context): Boolean = false

    @Suppress("UNUSED_PARAMETER")
    suspend fun track(ctx: Context, uri: Uri, doc: TrackDoc, pick: FreePick, onProgress: (Int, Int, Double) -> Unit): PointTrack? = null
}
