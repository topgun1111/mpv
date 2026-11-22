package com.takipli.oynat

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import android.content.Context
import android.graphics.Bitmap
import com.takipli.oynat.core.REID_DIM
import com.takipli.oynat.core.reidSimilarity
import java.nio.FloatBuffer

/**
 * Qualcomm OSNet x1.0, MIT-licensed, trained for person re-identification.
 * Offline CPU inference avoids blocking a pose scan on the first QNN compilation.
 * Input: RGB 0..1, NCHW [1,3,256,128]; output: L2-normalized [1,512].
 */
class NeuralReid(ctx: Context) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val model = Qnn.open(ctx, "osnet-reid.onnx", threads = 2, wantNpu = false)
    private val pixels = IntArray(256 * 128)
    private val chw = FloatArray(3 * pixels.size)

    init {
        try {
            require(model.inputNames() == setOf("image")) { "unexpected OSNet inputs" }
            require(model.inputShape("image").contentEquals(longArrayOf(1, 3, 256, 128))) { "unexpected OSNet shape" }
            require(model.outputShape("embeddings").contentEquals(longArrayOf(1, REID_DIM.toLong()))) { "unexpected OSNet output" }
        } catch (error: Throwable) {
            model.close()
            throw error
        }
    }

    /** A clean person detection, normalized x1/y1/x2/y2; never keeps the cropped image. */
    fun describe(image: Bitmap, box: List<Double>): List<Double>? {
        if (box.size < 4 || image.width <= 0 || image.height <= 0 || box.take(4).any { !it.isFinite() }) return null
        val left = (box[0] * image.width).toInt().coerceIn(0, image.width - 1)
        val top = (box[1] * image.height).toInt().coerceIn(0, image.height - 1)
        val right = (box[2] * image.width).toInt().coerceIn(0, image.width)
        val bottom = (box[3] * image.height).toInt().coerceIn(0, image.height)
        if (right - left < 16 || bottom - top < 48) return null
        val crop = Bitmap.createBitmap(image, left, top, right - left, bottom - top)
        try {
            val scaled = Bitmap.createScaledBitmap(crop, 128, 256, true)
            try {
                scaled.getPixels(pixels, 0, 128, 0, 0, 128, 256)
            } finally {
                if (scaled !== image && scaled !== crop) scaled.recycle()
            }
        } finally {
            if (crop !== image) crop.recycle()
        }
        val plane = pixels.size
        for (i in pixels.indices) {
            val c = pixels[i]
            chw[i] = ((c shr 16) and 255) / 255f
            chw[plane + i] = ((c shr 8) and 255) / 255f
            chw[2 * plane + i] = (c and 255) / 255f
        }
        OnnxTensor.createTensor(env, FloatBuffer.wrap(chw), longArrayOf(1, 3, 256, 128)).use { input ->
            model.run(mapOf("image" to input)).use { outputs ->
                val tensor = outputs.get("embeddings").get() as OnnxTensor
                val buffer = tensor.floatBuffer
                if (buffer.remaining() != REID_DIM) return null
                val values = FloatArray(REID_DIM)
                buffer.get(values)
                val vector = values.map { it.toDouble() }
                return vector.takeIf { reidSimilarity(it, it) != null }
            }
        }
    }

    override fun close() = model.close()
}
