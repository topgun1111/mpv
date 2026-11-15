package com.takipli.oynat

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.takipli.oynat.core.CoreInfo

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    var screen by remember { mutableStateOf("home") }
                    var resultFile by remember { mutableStateOf("") }
                    var selectedMode by remember { mutableStateOf("body") }
                    when (screen) {
                        "bench" -> BenchScreen(onBack = { screen = "home" })
                        "decode" -> DecodeScreen(onBack = { screen = "home" })
                        "scan" -> ScanScreen(onBack = { screen = "home" })
                        "pick" -> PickScreen(initialMode = selectedMode, onBack = { screen = "home" }, onResult = { resultFile = it; screen = "result" })
                        "record" -> RecordScreen(onBack = { screen = "home" })
                        "result" -> ResultScreen(resultFile, onBack = { screen = "pick" })
                        "update" -> UpdateScreen(onBack = { screen = "home" })
                        else -> HomeScreen(
                            onBench = { screen = "bench" }, onDecode = { screen = "decode" },
                            onScan = { screen = "scan" }, onPick = { mode -> selectedMode = mode; screen = "pick" }, onRecord = { screen = "record" }, onUpdate = { screen = "update" },
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun HomeScreen(onBench: () -> Unit, onDecode: () -> Unit, onScan: () -> Unit, onPick: (String) -> Unit, onRecord: () -> Unit, onUpdate: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text("TAKİPLİ OYNAT", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                Text(stringResource(R.string.home_title), style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            }
            Text("◉", color = MaterialTheme.colorScheme.primary, fontSize = 34.sp)
        }
        Text(stringResource(R.string.home_subtitle), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)

        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(26.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
        ) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(stringResource(R.string.home_start_title), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onPrimaryContainer)
                Text(stringResource(R.string.home_start_desc), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
                Button(onClick = { onPick("body") }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.open_pick)) }
            }
        }

        Text(stringResource(R.string.home_modes_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            ModePreviewCard("🧍", stringResource(R.string.mode_body), stringResource(R.string.mode_body_desc), Modifier.weight(1f)) { onPick("body") }
            ModePreviewCard("✦", stringResource(R.string.mode_point), stringResource(R.string.mode_point_desc), Modifier.weight(1f)) { onPick("point") }
        }
        ModePreviewCard("〰", stringResource(R.string.mode_freehand), stringResource(R.string.mode_freehand_desc), Modifier.fillMaxWidth()) { onPick("freehand") }
        ModePreviewCard("🎥", stringResource(R.string.mode_record), stringResource(R.string.mode_record_desc), Modifier.fillMaxWidth()) { onRecord() }

        Text(stringResource(R.string.home_tools_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = onBench, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.open_bench)) }
            OutlinedButton(onClick = onDecode, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.open_decode)) }
        }
        OutlinedButton(onClick = onScan, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.open_scan)) }
        OutlinedButton(onClick = onUpdate, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.open_update)) }
        Text(stringResource(R.string.version_label, BuildConfig.VERSION_NAME) + "  ·  " + stringResource(R.string.core_check, CoreInfo.label()), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        AboutSection()
    }
}

@Composable
private fun ModePreviewCard(icon: String, title: String, description: String, modifier: Modifier, onClick: () -> Unit) {
    Card(onClick = onClick, modifier = modifier, shape = RoundedCornerShape(20.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(icon, fontSize = 25.sp)
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Text(description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
