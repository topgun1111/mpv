package com.takipli.oynat.core

import java.io.IOException
import java.util.Base64
import kotlin.io.path.createTempDirectory
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class UpdateTest {
    @Test
    fun parsesReleaseAssetNamesForTheOwnEngineOnly() {
        assertEquals("1.2.0-b45" to 10_200_045, parseUpdateAsset("TakipliOynat-Android-sam-1.2.0-b45.apk", "sam"))
        assertNull(parseUpdateAsset("TakipliOynat-Android-pose-1.2.0-b45.apk", "sam"))
        assertNull(parseUpdateAsset("TakipliOynat-Android-sam-1.2.0-debug.apk", "sam"))
        assertNull(parseUpdateAsset("TakipliOynat-Android-sam-1.2.0.apk", "sam"))
    }

    @Test
    fun parsesRecorderApksOnly() {
        assertEquals("1.2.0-b45" to 10_200_045, parseRecordingUpdateAsset("TakipliKayit-Android-1.2.0-b45.apk"))
        assertNull(parseRecordingUpdateAsset("TakipliOynat-Android-sam-1.2.0-b45.apk"))
        assertNull(parseRecordingUpdateAsset("TakipliKayit-Android-1.2.0-b1000.apk"))
        assertNull(parseRecordingUpdateAsset("TakipliKayit-Android-999.99.99-b45.apk"))
    }

    @Test
    fun appliesReleasePatchByteForByteAndRejectsBadInput() {
        val dir = createTempDirectory().toFile()
        try {
            val base = dir.resolve("base.apk").apply { writeText("unchanged+old") }
            // Gzip fixture follows the release generator format and uses both copy and literal records.
            val patch = dir.resolve("update.patch").apply {
                writeBytes(Base64.getDecoder().decode(
                    "H4sIAAAAAAACAwtwdnH1CXE0ZHDMDuC7cnarwrzD7tKGjLYuPwov59UYPbpfKRBhJ7Ssyu" +
                    "Dlra7SBO68b1y+2SFcISUhXxXfLjd7E3KIv+y6dP8aHQYI4GVAAlyMQII5L7WcCQAYiHvw" +
                    "ZgAAAA==",
                ))
            }
            val output = dir.resolve("out.apk")
            val baseSha = "00416b500ed4cdb5209ec3471b31013d44f871d36e7c32e2df7910583e12a67a"
            val targetSha = "30e9da8a75600b6ef60a4d6b540a547454f521eda736ec54c20f76d71b8fac2c"
            ApkDelta.apply(base, patch, output, baseSha, targetSha, 13)
            assertContentEquals("unchanged+new".encodeToByteArray(), output.readBytes())

            base.writeText("unchanged+bad")
            assertFailsWith<IOException> { ApkDelta.apply(base, patch, output, baseSha, targetSha, 13) }
            assertFalse(output.exists())
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test
    fun buildNumberOrdersBuildsAndVersions() {
        assertEquals(10_200_999, updateVersionCode("1.2.0", 5000)) // capped
        assertTrue(updateVersionCode("1.2.0", 46) > updateVersionCode("1.2.0", 45))
        assertTrue(updateVersionCode("1.2.1", 0) > updateVersionCode("1.2.0", 999))
    }
}
