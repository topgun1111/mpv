package com.takipli.oynat.core

/** Independent grading controls; ranges and presets mirror Windows Editing. */
enum class GradeControl(val label: String, val min: Int, val max: Int) {
    HAZE("Dehaze", 0, 40),
    CONTRAST("Contrast", -30, 30),
    BRIGHTNESS("Brightness", -20, 20),
    GAMMA("Gamma", -30, 30),
    SATURATION("Saturation", -50, 50),
    SHADOWS("Shadows", -20, 20),
    HIGHLIGHTS("Highlights", -20, 20),
    WARMTH("Warmth", -20, 20),
    CLARITY("Clarity", 0, 60),
    SHARPNESS("Sharpness", 0, 60),
    DENOISE("Denoise", 0, 40),
}

data class Grade(val values: Map<GradeControl, Int> = emptyMap()) {
    operator fun get(control: GradeControl): Int = (values[control] ?: 0).coerceIn(control.min, control.max)
    fun with(control: GradeControl, value: Int): Grade =
        Grade(values + (control to value.coerceIn(control.min, control.max)))
    fun neutral(): Boolean = GradeControl.entries.all { this[it] == 0 }
    fun uniforms(): FloatArray = GradeControl.entries.map { this[it] / 100f }.toFloatArray()
}

enum class HazePreset(val label: String, val grade: Grade) {
    LIGHT("Light", Grade(mapOf(GradeControl.HAZE to 8, GradeControl.SATURATION to 5,
        GradeControl.CLARITY to 15, GradeControl.SHARPNESS to 10))),
    MODERATE("Moderate", Grade(mapOf(GradeControl.HAZE to 16, GradeControl.SATURATION to 10,
        GradeControl.CLARITY to 25, GradeControl.SHARPNESS to 15, GradeControl.HIGHLIGHTS to -5))),
    STRONG("Strong", Grade(mapOf(GradeControl.HAZE to 28, GradeControl.SATURATION to 15,
        GradeControl.CLARITY to 35, GradeControl.SHARPNESS to 20, GradeControl.HIGHLIGHTS to -10))),
}

enum class GradeQuality(val label: String, val factor: Double) {
    MAXIMUM("Maximum", 1.6), HIGH("High", 1.0), BALANCED("Balanced", 0.65),
    SMALL("Small file", 0.35), CUSTOM("Custom", 1.0);
}

/** Android uses a target bitrate, not desktop FFmpeg CRF. Bound output before codec validation. */
fun gradeBitrate(base: Int, quality: GradeQuality, customMbps: Int): Int =
    if (quality == GradeQuality.CUSTOM) customMbps.coerceIn(2, 100) * 1_000_000
    else (base.coerceIn(2_000_000, 100_000_000) * quality.factor)
        .coerceIn(2_000_000.0, 100_000_000.0).toInt()
