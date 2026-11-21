package com.takipli.oynat.core

/** SAM decodes N frames, then visits N+1 frames (the picked frame twice). */
class SamPassCounter(private val frames: Int) {
    init { require(frames > 0 && frames <= (Int.MAX_VALUE - 1) / 2) }
    val total: Int = frames * 2 + 1
    private var tracked = 0

    fun next(): Int {
        check(tracked <= frames) { "SAM tracking called more than N+1 times" }
        tracked++
        return frames + tracked
    }
}
