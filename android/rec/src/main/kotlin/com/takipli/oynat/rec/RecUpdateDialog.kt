package com.takipli.oynat.rec

import android.text.format.Formatter
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.io.File

@Composable
internal fun RecUpdateDialog(onClose: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var checking by remember { mutableStateOf(true) }
    var downloading by remember { mutableStateOf(false) }
    var retry by remember { mutableStateOf(0) }
    var update by remember { mutableStateOf<RecUpdater.Update?>(null) }
    var apk by remember { mutableStateOf<File?>(null) }
    var progress by remember { mutableStateOf(0) }
    var status by remember { mutableStateOf("") }

    fun fail(e: Exception) {
        status = ctx.getString(R.string.rec_update_error, e.message ?: e.javaClass.simpleName)
    }

    LaunchedEffect(retry) {
        checking = true
        status = ""
        try {
            update = RecUpdater.check(ctx)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            fail(e)
        } finally {
            checking = false
        }
    }

    val found = update
    val file = apk
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(stringResource(R.string.rec_update_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                when {
                    checking -> Text(stringResource(R.string.rec_update_checking))
                    found != null -> {
                        Text(stringResource(R.string.rec_update_found, found.label))
                        val patch = found.patch
                        if (patch != null) {
                            Text(stringResource(R.string.rec_update_sizes,
                                Formatter.formatShortFileSize(ctx, patch.bytes),
                                Formatter.formatShortFileSize(ctx, found.apkBytes)))
                        } else {
                            Text(stringResource(R.string.rec_update_no_patch))
                        }
                    }
                    status.isEmpty() -> Text(stringResource(R.string.rec_update_current))
                }
                if (downloading) {
                    Text(stringResource(if (progress < 100) R.string.rec_update_downloading else R.string.rec_update_verifying))
                    LinearProgressIndicator(progress = { progress / 100f }, modifier = Modifier.fillMaxWidth())
                }
                if (status.isNotEmpty()) Text(status)
            }
        },
        confirmButton = {
            when {
                file != null -> Button(onClick = {
                    try {
                        if (ctx.packageManager.canRequestPackageInstalls()) {
                            status = ""
                            RecUpdater.install(ctx, file)
                        } else {
                            status = ctx.getString(R.string.rec_update_permission)
                            RecUpdater.openInstallerSettings(ctx)
                        }
                    } catch (e: Exception) { fail(e) }
                }) { Text(stringResource(R.string.rec_update_install)) }
                found?.patch != null && !downloading -> Button(onClick = {
                    status = ""
                    progress = 0
                    downloading = true
                    scope.launch {
                        try {
                            apk = RecUpdater.download(ctx, found) { progress = it }
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Exception) {
                            fail(e)
                        } finally {
                            downloading = false
                        }
                    }
                }) { Text(stringResource(R.string.rec_update_download)) }
                found != null && found.patch == null -> Button(onClick = {
                    try { RecUpdater.openRelease(ctx, found) } catch (e: Exception) { fail(e) }
                }) { Text(stringResource(R.string.rec_update_release)) }
                !checking && found == null && status.isNotEmpty() -> Button(onClick = { retry++ }) {
                    Text(stringResource(R.string.rec_update_retry))
                }
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text(stringResource(android.R.string.cancel)) } },
    )
}
