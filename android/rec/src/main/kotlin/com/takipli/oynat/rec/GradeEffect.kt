package com.takipli.oynat.rec

import android.content.Context
import android.opengl.GLES20
import androidx.media3.common.VideoFrameProcessingException
import androidx.media3.common.util.GlProgram
import androidx.media3.common.util.GlUtil
import androidx.media3.common.util.Size
import androidx.media3.effect.BaseGlShaderProgram
import androidx.media3.effect.GlEffect
import androidx.media3.effect.GlShaderProgram
import com.takipli.oynat.core.Grade

/**
 * One GPU pass for both preview and export. Media3 provides linear SDR RGB.
 * Process in an approximate display-gamma space, then return linear RGB.
 * The preview reads an atomic snapshot; export receives an immutable snapshot.
 */
internal class GradeEffect(private val settings: () -> Grade) : GlEffect {
    override fun toGlShaderProgram(context: Context, useHdr: Boolean): GlShaderProgram {
        if (useHdr) throw VideoFrameProcessingException("Editing supports SDR video only")
        return GradeProgram(settings)
    }
}

private class GradeProgram(private val settings: () -> Grade) : BaseGlShaderProgram(false, 1) {
    private val gl = GlProgram(VERTEX, FRAGMENT)
    private var width = 1
    private var height = 1

    init {
        gl.setBufferAttribute("aPosition", floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f), 2)
    }

    override fun configure(inputWidth: Int, inputHeight: Int): Size {
        width = inputWidth.coerceAtLeast(1)
        height = inputHeight.coerceAtLeast(1)
        return Size(inputWidth, inputHeight)
    }

    override fun drawFrame(inputTexId: Int, presentationTimeUs: Long) {
        try {
            val v = settings().uniforms()
            gl.use()
            gl.setSamplerTexIdUniform("uTex", inputTexId, 0)
            gl.setFloatsUniform("uPixel", floatArrayOf(1f / width, 1f / height))
            gl.setFloatsUniform("uTone", floatArrayOf(v[0], v[1], v[2], v[3]))
            gl.setFloatsUniform("uColor", floatArrayOf(v[4], v[5], v[6], v[7]))
            gl.setFloatsUniform("uDetail", floatArrayOf(v[8], v[9], v[10]))
            gl.bindAttributesAndUniforms()
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
            GlUtil.checkGlError()
        } catch (e: Exception) {
            throw VideoFrameProcessingException.from(e, presentationTimeUs)
        }
    }

    override fun release() {
        try { gl.delete() } finally { super.release() }
    }
}

private const val VERTEX = """
attribute vec2 aPosition;
varying vec2 vUv;
void main() {
    gl_Position = vec4(aPosition, 0.0, 1.0);
    vUv = aPosition * 0.5 + 0.5;
}
"""

private const val FRAGMENT = """
precision highp float;
uniform sampler2D uTex;
uniform vec2 uPixel;
uniform vec4 uTone;
uniform vec4 uColor;
uniform vec3 uDetail;
varying vec2 vUv;

vec3 sampleAt(vec2 p) {
    return pow(max(texture2D(uTex, clamp(p, vec2(0.0), vec2(1.0))).rgb, vec3(0.0)), vec3(1.0/2.2));
}
vec3 crossBlur(vec2 d) {
    return (sampleAt(vUv + vec2(d.x, 0.0)) + sampleAt(vUv - vec2(d.x, 0.0))
          + sampleAt(vUv + vec2(0.0, d.y)) + sampleAt(vUv - vec2(0.0, d.y))) * 0.25;
}
void main() {
    if (all(equal(uTone, vec4(0.0))) && all(equal(uColor, vec4(0.0))) &&
        all(equal(uDetail, vec3(0.0)))) {
        gl_FragColor = texture2D(uTex, vUv);
        return;
    }
    vec3 rgb = sampleAt(vUv);
    // Edge-aware spatial noise reduction and two scales of local contrast.
    if (uDetail.y > 0.0 || uDetail.z > 0.0) {
        vec3 nearBlur = crossBlur(uPixel);
        float delta = length(rgb - nearBlur);
        rgb = mix(rgb, nearBlur, uDetail.z * (1.0 - smoothstep(0.03, 0.20, delta)));
        rgb += (rgb - nearBlur) * uDetail.y;
    }
    if (uDetail.x > 0.0) {
        rgb += (rgb - crossBlur(uPixel * 5.0)) * uDetail.x;
    }
    float invT = 1.0 / (1.0 - uTone.x);
    rgb = (rgb - 0.5) * invT * (1.0 + uTone.y) + 0.5
          - 0.5 * (invT - 1.0) + uTone.z;
    rgb = pow(clamp(rgb, 0.0, 1.0), vec3(1.0 / (1.0 + uTone.w)));
    float luma = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
    float shadow = 1.0 - smoothstep(0.0, 0.65, luma);
    float highlight = smoothstep(0.35, 1.0, luma);
    rgb += vec3((uColor.y * shadow + uColor.z * highlight) * 4.0 * luma * (1.0 - luma));
    luma = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
    rgb = mix(vec3(luma), rgb, 1.0 + uColor.x);
    rgb += vec3(uColor.w * 0.5, 0.0, -uColor.w * 0.5);
    gl_FragColor = vec4(pow(clamp(rgb, 0.0, 1.0), vec3(2.2)), 1.0);
}
"""
