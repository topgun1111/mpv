package com.takipli.oynat.rec

import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.takipli.oynat.core.GradeQuality
import com.takipli.oynat.core.gradeBitrate
import kotlin.math.ceil
import kotlin.math.roundToInt

internal data class RecExportQuality(
    val preset: GradeQuality = GradeQuality.HIGH,
    val customMbps: Int = 20,
) {
    fun bitrate(info: VideoInfo): Int {
        val source = checkNotNull(info.bitrate)
        return gradeBitrate(source, preset, maxOf(customMbps, ceil(source / 1e6).toInt()))
    }
}

@Composable
internal fun RecExportOptions(
    info: VideoInfo,
    quality: RecExportQuality,
    onChange: (RecExportQuality) -> Unit,
    onDismiss: () -> Unit,
    onExport: () -> Unit,
    extraOptions: @Composable () -> Unit = {},
) {
    val source = info.bitrate
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.export_options)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (source == null) {
                    Text(stringResource(R.string.export_bitrate_unknown))
                } else {
                    Text(stringResource(R.string.export_source_info, info.width, info.height, source / 1e6))
                    Column(Modifier.selectableGroup()) {
                        for (preset in GradeQuality.entries) {
                            val label = when (preset) {
                                GradeQuality.SOURCE -> R.string.export_quality_source
                                GradeQuality.HIGH -> R.string.export_quality_high
                                GradeQuality.MAXIMUM -> R.string.export_quality_maximum
                                GradeQuality.CUSTOM -> R.string.export_quality_custom
                            }
                            val selected = quality.preset == preset
                            Row(
                                Modifier.fillMaxWidth().heightIn(min = 48.dp).selectable(selected, role = Role.RadioButton) {
                                    onChange(quality.copy(preset = preset))
                                },
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(12.dp),
                            ) {
                                RadioButton(selected = selected, onClick = null)
                                Text(stringResource(label))
                            }
                        }
                    }
                    if (quality.preset == GradeQuality.CUSTOM) {
                        val minMbps = ceil(source / 1e6).toInt()
                        val maxMbps = maxOf(100, ceil(gradeBitrate(source, GradeQuality.MAXIMUM, 0) / 1e6).toInt())
                        if (maxMbps > minMbps) {
                            Slider(
                                value = quality.customMbps.coerceIn(minMbps, maxMbps).toFloat(),
                                onValueChange = { onChange(quality.copy(customMbps = it.roundToInt())) },
                                valueRange = minMbps.toFloat()..maxMbps.toFloat(),
                            )
                        }
                    }
                    Text(stringResource(R.string.export_target_info, quality.bitrate(info) / 1e6))
                    extraOptions()
                }
            }
        },
        confirmButton = { Button(onClick = onExport, enabled = source != null) { Text(stringResource(R.string.export_mp4)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(android.R.string.cancel)) } },
    )
}
