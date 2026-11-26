package com.takipli.oynat.rec

import android.content.Context
import android.net.Uri
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.transformer.Composition
import androidx.media3.transformer.DefaultEncoderFactory
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.EncoderSelector
import androidx.media3.transformer.EncoderUtil
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import androidx.media3.transformer.VideoEncoderSettings
import com.google.common.collect.ImmutableList
import com.takipli.oynat.core.Grade
import com.takipli.oynat.core.GradeQuality
import com.takipli.oynat.core.gradeBitrate
import java.io.File

internal enum class EditEncoder(val label: String) {
    AUTO("Auto"), HARDWARE("Hardware"), SOFTWARE("Software")
}

internal data class EditOutput(
    val quality: GradeQuality = GradeQuality.HIGH,
    val customMbps: Int = 20,
    val hevc: Boolean = false,
    val encoder: EditEncoder = EditEncoder.AUTO,
) {
    val mime: String get() = if (hevc) MimeTypes.VIDEO_H265 else MimeTypes.VIDEO_H264
    fun bitrate(info: VideoInfo): Int = gradeBitrate(
        RecExporter.targetBitrate(info.bitrate, info.width, info.height,
            (info.frameRate ?: 30.0).coerceIn(1.0, 60.0), hevc),
        quality, customMbps,
    )
}

internal object EditExporter {
    fun start(
        ctx: Context, source: Uri, info: VideoInfo, grade: Grade, options: EditOutput, file: File,
        onDone: (ExportResult) -> Unit, onError: (ExportException) -> Unit,
    ): Transformer {
        require(!info.hdr) { "Editing supports SDR video only" }
        val encoders = EncoderUtil.getSupportedEncoders(options.mime)
        require(encoders.any {
            when (options.encoder) {
                EditEncoder.AUTO -> true
                EditEncoder.HARDWARE -> it.isHardwareAccelerated
                EditEncoder.SOFTWARE -> it.isSoftwareOnly
            }
        }) { "Selected encoder is not available for this codec" }
        val selector = EncoderSelector { mime ->
            val available = EncoderUtil.getSupportedEncoders(mime)
            val chosen = when (options.encoder) {
                EditEncoder.AUTO -> available.sortedByDescending { it.isHardwareAccelerated }
                EditEncoder.HARDWARE -> available.filter { it.isHardwareAccelerated }
                EditEncoder.SOFTWARE -> available.filter { it.isSoftwareOnly }
            }
            ImmutableList.copyOf(chosen)
        }
        val encoder = DefaultEncoderFactory.Builder(ctx)
            .setVideoEncoderSelector(selector)
            .setRequestedVideoEncoderSettings(
                VideoEncoderSettings.Builder().setBitrate(options.bitrate(info)).build(),
            )
            .build()
        // Always force a frame-processing effect, even for a neutral grade, so requested
        // bitrate/encoder is used rather than transmuxing the unchanged source.
        val item = EditedMediaItem.Builder(MediaItem.fromUri(source))
            .setEffects(Effects(emptyList(), listOfNotNull(RecExporter.rotationEffect(info.userRot), GradeEffect { grade })))
            .build()
        val t = Transformer.Builder(ctx)
            .setVideoMimeType(options.mime)
            .setEncoderFactory(encoder)
            .addListener(object : Transformer.Listener {
                override fun onCompleted(composition: Composition, exportResult: ExportResult) = onDone(exportResult)
                override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) = onError(exportException)
            }).build()
        file.parentFile?.mkdirs()
        check(!file.exists()) { "Export temporary file already exists" }
        t.start(item, file.absolutePath)
        return t
    }
}
