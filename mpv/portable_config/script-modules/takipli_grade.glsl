//!PARAM tg_haze
//!TYPE float
//!MINIMUM 0
//!MAXIMUM 0.4
0.0

//!PARAM tg_contrast
//!TYPE float
//!MINIMUM -0.3
//!MAXIMUM 0.3
0.0

//!PARAM tg_brightness
//!TYPE float
//!MINIMUM -0.2
//!MAXIMUM 0.2
0.0

//!PARAM tg_gamma
//!TYPE float
//!MINIMUM -0.3
//!MAXIMUM 0.3
0.0

//!PARAM tg_saturation
//!TYPE float
//!MINIMUM -0.5
//!MAXIMUM 0.5
0.0

//!PARAM tg_shadows
//!TYPE float
//!MINIMUM -0.2
//!MAXIMUM 0.2
0.0

//!PARAM tg_highlights
//!TYPE float
//!MINIMUM -0.2
//!MAXIMUM 0.2
0.0

//!PARAM tg_warmth
//!TYPE float
//!MINIMUM -0.2
//!MAXIMUM 0.2
0.0

//!PARAM tg_clarity
//!TYPE float
//!MINIMUM 0
//!MAXIMUM 0.6
0.0

//!PARAM tg_sharpness
//!TYPE float
//!MINIMUM 0
//!MAXIMUM 0.6
0.0

//!PARAM tg_denoise
//!TYPE float
//!MINIMUM 0
//!MAXIMUM 0.4
0.0

//!HOOK MAIN
//!BIND HOOKED
//!DESC Takipli GPU grading preview
// SDR display-referred grading approximation; export retains the FFmpeg filter chain.
// Nine texture reads maximum, independent of radius; no full-frame CPU readback.
float grade_luma(vec3 rgb) { return dot(rgb, vec3(0.2126, 0.7152, 0.0722)); }
vec4 hook() {
    vec4 src = HOOKED_tex(HOOKED_pos);
    vec3 rgb = src.rgb;
    float y = grade_luma(rgb);
    if (tg_denoise > 0.0 || tg_sharpness > 0.0) {
        vec3 near_avg = 0.25 * (
            HOOKED_texOff(vec2(-1.0, 0.0)).rgb + HOOKED_texOff(vec2(1.0, 0.0)).rgb +
            HOOKED_texOff(vec2(0.0, -1.0)).rgb + HOOKED_texOff(vec2(0.0, 1.0)).rgb);
        if (tg_denoise > 0.0) {
            float blend = min(0.65, tg_denoise * 1.5) *
                (1.0 - smoothstep(0.015, 0.12, abs(y - grade_luma(near_avg))));
            rgb = mix(rgb, near_avg, blend);
        }
        rgb += vec3((grade_luma(rgb) - grade_luma(near_avg)) * tg_sharpness * 3.3333);
    }
    if (tg_clarity > 0.0) {
        float far_avg = 0.25 * (
            grade_luma(HOOKED_texOff(vec2(-5.0, 0.0)).rgb) +
            grade_luma(HOOKED_texOff(vec2(5.0, 0.0)).rgb) +
            grade_luma(HOOKED_texOff(vec2(0.0, -5.0)).rgb) +
            grade_luma(HOOKED_texOff(vec2(0.0, 5.0)).rgb));
        rgb += vec3((y - far_avg) * tg_clarity * 2.5);
    }
    float transmission = max(0.6, 1.0 - tg_haze);
    float contrast = (1.0 + tg_contrast) / transmission;
    float brightness = -0.5 * (1.0 / transmission - 1.0) + tg_brightness;
    rgb = clamp((rgb - vec3(0.5)) * contrast + vec3(0.5 + brightness), 0.0, 1.0);
    rgb = pow(rgb, vec3(1.0 / (1.0 + tg_gamma)));
    float lum = grade_luma(rgb);
    rgb = mix(vec3(lum), rgb, 1.0 + tg_saturation);
    float shadow = max(0.0, 1.0 - abs(lum - 0.25) * 4.0);
    float highlight = max(0.0, 1.0 - abs(lum - 0.75) * 4.0);
    rgb += vec3(shadow * tg_shadows + highlight * tg_highlights);
    rgb += vec3(1.0, 0.0, -1.0) * tg_warmth * (0.5 + 2.0 * lum * (1.0-lum));
    return vec4(clamp(rgb, 0.0, 1.0), src.a);
}
