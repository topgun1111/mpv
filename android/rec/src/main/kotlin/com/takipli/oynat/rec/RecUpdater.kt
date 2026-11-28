package com.takipli.oynat.rec

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import com.takipli.oynat.core.ApkDelta
import com.takipli.oynat.core.parseRecordingUpdateAsset
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

internal object RecUpdater {
    data class Patch(val url: String, val bytes: Long, val sha256: String)
    data class Update(
        val label: String,
        val code: Int,
        val releaseUrl: String,
        val apkBytes: Long,
        val apkSha: String,
        val installedSha: String,
        val patch: Patch?,
    )

    private const val REPO = BuildConfig.UPDATE_REPO
    private val shaPattern = Regex("[0-9a-f]{64}")
    private fun JSONObject.sha256(): String =
        optString("digest").removePrefix("sha256:").takeIf(shaPattern::matches).orEmpty()

    private fun open(url: URL): HttpURLConnection = (url.openConnection() as HttpURLConnection).apply {
        connectTimeout = 15_000
        readTimeout = 30_000
        instanceFollowRedirects = false
        setRequestProperty("User-Agent", "TakipliKayit-Android")
    }

    suspend fun check(ctx: Context): Update? = withContext(Dispatchers.IO) {
        val conn = open(URL("https://api.github.com/repos/$REPO/releases?per_page=20"))
        val releases = try {
            conn.setRequestProperty("Accept", "application/vnd.github+json")
            if (conn.responseCode != 200) throw IOException("HTTP ${conn.responseCode}")
            JSONArray(conn.inputStream.bufferedReader().use { it.readText() })
        } finally {
            conn.disconnect()
        }
        var newestCode = BuildConfig.VERSION_CODE
        var newestLabel = ""
        var newestRelease: JSONObject? = null
        var newestApk: JSONObject? = null
        for (i in 0 until releases.length()) {
            val release = releases.getJSONObject(i)
            if (release.optBoolean("draft")) continue
            val assets = release.optJSONArray("assets") ?: continue
            for (j in 0 until assets.length()) {
                val asset = assets.getJSONObject(j)
                val (label, code) = parseRecordingUpdateAsset(asset.optString("name")) ?: continue
                if (code > newestCode) {
                    newestCode = code
                    newestLabel = label
                    newestRelease = release
                    newestApk = asset
                }
            }
        }
        val release = newestRelease ?: return@withContext null
        val apk = checkNotNull(newestApk)
        val apkSha = apk.sha256()
        val apkBytes = apk.optLong("size")
        val releaseUrl = "https://github.com/$REPO/releases/tag/${Uri.encode(release.getString("tag_name"))}"
        val assets = release.getJSONArray("assets")
        val installedSha = if (apkSha.isNotEmpty() && apkBytes in 1..ApkDelta.MAX_APK) {
            ApkDelta.sha256(File(ctx.applicationInfo.sourceDir)) { ensureActive(); false }
        } else ""
        var patch: Patch? = null
        for (i in 0 until assets.length()) {
            val asset = assets.getJSONObject(i)
            if (installedSha.isEmpty() || asset.optString("name") != "TakipliKayit-Patch-$installedSha-$apkSha-$newestLabel.patch") continue
            val url = asset.optString("browser_download_url")
            val bytes = asset.optLong("size")
            val sha = asset.sha256()
            if (url.startsWith("https://github.com/$REPO/releases/download/") && bytes in 1 until apkBytes && sha.isNotEmpty()) {
                patch = Patch(url, bytes, sha)
                break
            }
        }
        Update(newestLabel, newestCode, releaseUrl, apkBytes, apkSha, installedSha, patch)
    }

    private fun patchConnection(source: String): HttpURLConnection {
        var url = URL(source)
        repeat(6) {
            if (url.protocol != "https" ||
                (url.host != "github.com" && !url.host.endsWith(".githubusercontent.com"))
            ) throw IOException("Invalid GitHub asset host")
            val conn = open(url)
            var keep = false
            try {
                when (val status = conn.responseCode) {
                    200 -> {
                        keep = true
                        return conn
                    }
                    301, 302, 303, 307, 308 -> {
                        val location = conn.getHeaderField("Location") ?: throw IOException("Missing redirect URL")
                        url = URL(url, location)
                    }
                    else -> throw IOException("HTTP $status")
                }
            } finally {
                if (!keep) conn.disconnect()
            }
        }
        throw IOException("Too many redirects")
    }

    suspend fun download(ctx: Context, update: Update, progress: (Int) -> Unit): File = withContext(Dispatchers.IO) {
        val patch = checkNotNull(update.patch)
        val dir = File(ctx.cacheDir, "updates")
        check(dir.isDirectory || dir.mkdirs()) { "Cannot create update cache" }
        val output = File(dir, "TakipliKayit-${update.apkSha}.apk")
        val active: () -> Boolean = { ensureActive(); false }
        if (output.isFile && ApkDelta.sha256(output, active) == update.apkSha) return@withContext output
        val downloaded = File.createTempFile("patch-", ".part", dir)
        val reconstructed = File(dir, "${downloaded.name}.apk")
        try {
            val conn = patchConnection(patch.url)
            try {
                conn.inputStream.use { input ->
                    downloaded.outputStream().buffered().use { out ->
                        val buffer = ByteArray(64 * 1024)
                        var received = 0L
                        var percent = 0
                        while (true) {
                            ensureActive()
                            val size = input.read(buffer)
                            if (size == -1) break
                            received += size
                            if (received > patch.bytes) throw IOException("Patch size mismatch")
                            out.write(buffer, 0, size)
                            val next = (received * 100 / patch.bytes).toInt()
                            if (next != percent) {
                                progress(next)
                                percent = next
                            }
                        }
                    }
                }
            } finally {
                conn.disconnect()
            }
            if (downloaded.length() != patch.bytes || ApkDelta.sha256(downloaded, active) != patch.sha256) {
                throw IOException("Patch checksum mismatch")
            }
            ApkDelta.apply(File(ctx.applicationInfo.sourceDir), downloaded, reconstructed, update.installedSha,
                update.apkSha, update.apkBytes, active)
            val info = ctx.packageManager.getPackageArchiveInfo(reconstructed.absolutePath, 0)
            if (info == null || info.packageName != ctx.packageName || info.longVersionCode != update.code.toLong()) {
                throw IOException("APK package or version mismatch")
            }
            ensureActive()
            check(reconstructed.renameTo(output)) { "Cannot save verified update" }
            // Keep at most one completed update in this private cache.
            dir.listFiles()?.filter { it != output && it.name.startsWith("TakipliKayit-") }?.forEach { it.delete() }
            output
        } finally {
            downloaded.delete()
            reconstructed.delete()
        }
    }

    fun openInstallerSettings(ctx: Context) {
        ctx.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${ctx.packageName}")))
    }

    fun install(ctx: Context, apk: File) {
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.updates", apk)
        ctx.startActivity(Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
    }

    fun openRelease(ctx: Context, update: Update) {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(update.releaseUrl)))
    }
}
