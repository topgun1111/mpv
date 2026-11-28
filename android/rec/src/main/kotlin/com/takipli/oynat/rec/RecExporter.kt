package com.takipli.oynat.rec

import android.content.ContentValues
import android.content.Context
import android.graphics.Matrix
import android.net.Uri
import android.provider.MediaStore
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.effect.MatrixTransformation
import androidx.media3.effect.ScaleAndRotateTransformation
import androidx.media3.transformer.Composition
import androidx.media3.transformer.DefaultEncoderFactory
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import androidx.media3.transformer.VideoEncoderSettings
import com.takipli.oynat.core.ViewKey
import com.takipli.oynat.core.exportNdc
import com.takipli.oynat.core.viewAtSmooth
import java.io.File

/**
 * Export of a recorded camera path with Media3 Transformer (same maths as the full app's `Exporter`, without stabilization):
 * manual turn first, then the time-varying zoom + pan matrix; frame size = (turned) source size; hardware encoder; audio passthrough.
 * Call [start] on the main thread; callbacks arrive there too.
 */
internal object RecExporter {
    /** The manual clockwise turn as a Media3 effect (Media3 rotates counterclockwise, hence the minus); null = none. Preview and export share it. */
    fun rotationEffect(userRot: Int): ScaleAndRotateTransformation? =
        if (userRot % 360 == 0) null else ScaleAndRotateTransformation.Builder().setRotationDegrees(-userRot.toFloat()).build()

    fun start(
        ctx: Context, source: Uri, views: List<ViewKey>, outFile: File,
        info: VideoInfo, quality: RecExportQuality,
        onDone: (ExportResult) -> Unit, onError: (ExportException) -> Unit,
    ): Transformer {
        outFile.parentFile?.mkdirs()
        outFile.delete()
        val crop = MatrixTransformation { us ->
            val n = exportNdc(viewAtSmooth(views, us / 1e6))
            Matrix().apply { setTranslate(n[1].toFloat(), n[2].toFloat()); postScale(n[0].toFloat(), n[0].toFloat()) }
        }
        val item = EditedMediaItem.Builder(MediaItem.fromUri(source))
            .setEffects(Effects(emptyList(), listOfNotNull(rotationEffect(info.userRot), crop)))
            .build()
        val encoder = DefaultEncoderFactory.Builder(ctx)
            .setEnableFallback(false)
            .setRequestedVideoEncoderSettings(VideoEncoderSettings.Builder().setBitrate(quality.bitrate(info)).build())
            .build()
        val transformer = Transformer.Builder(ctx)
            .setVideoMimeType(if (info.hevc || info.hdr) MimeTypes.VIDEO_H265 else MimeTypes.VIDEO_H264)
            .setEncoderFactory(encoder)
            .addListener(object : Transformer.Listener {
                override fun onCompleted(composition: Composition, exportResult: ExportResult) = onDone(exportResult)
                override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) = onError(exportException)
            })
            .build()
        transformer.start(item, outFile.absolutePath)
        return transformer
    }

    /** Check the encoder output before it reaches the gallery. Media3 can store rotation as metadata. */
    fun verifyQuality(ctx: Context, source: VideoInfo, file: File, result: ExportResult) {
        val sourceBitrate = checkNotNull(source.bitrate) { ctx.getString(R.string.export_bitrate_unknown) }
        val output = RecVideo.probe(ctx, Uri.fromFile(file))
        check(output.width == source.width && output.height == source.height) {
            ctx.getString(R.string.export_size_failed)
        }
        val outputBitrate = checkNotNull(output.bitrate) { ctx.getString(R.string.export_bitrate_unverified) }
        check(outputBitrate >= sourceBitrate) {
            ctx.getString(R.string.export_bitrate_failed, outputBitrate / 1e6, sourceBitrate / 1e6)
        }
        check(source.frameCount == null || (output.frameCount ?: result.videoFrameCount) >= source.frameCount) {
            ctx.getString(R.string.export_frames_failed)
        }
        check(!source.hdr || output.hdr) {
            ctx.getString(R.string.export_hdr_failed)
        }
    }

    /** 0..1, or -1 when the transformer cannot tell yet. Main thread only. */
    fun progress(t: Transformer): Float {
        val holder = ProgressHolder()
        return if (t.getProgress(holder) == Transformer.PROGRESS_STATE_AVAILABLE) holder.progress / 100f else -1f
    }

    /** Copies the finished file into Movies/TakipliOynat (MediaStore, no storage permission). */
    fun saveToMovies(ctx: Context, file: File, displayName: String): Uri {
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, displayName)
            put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
            put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/TakipliOynat")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val resolver = ctx.contentResolver
        val uri = checkNotNull(resolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)) { "cannot create the output file" }
        try {
            checkNotNull(resolver.openOutputStream(uri)) { "cannot open the output file" }.use { out -> file.inputStream().use { it.copyTo(out) } }
            resolver.update(uri, ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }, null, null)
        } catch (e: Throwable) {
            resolver.delete(uri, null, null)
            throw e
        }
        return uri
    }
}
