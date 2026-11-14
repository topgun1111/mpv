package com.takipli.oynat

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.takipli.oynat.core.CoreInfo

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    var screen by remember { mutableStateOf("home") }
                    when (screen) {
                        "bench" -> BenchScreen(onBack = { screen = "home" })
                        "decode" -> DecodeScreen(onBack = { screen = "home" })
                        else -> HomeScreen(onBench = { screen = "bench" }, onDecode = { screen = "decode" })
                    }
                }
            }
        }
    }
}

@Composable
fun HomeScreen(onBench: () -> Unit, onDecode: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, alignment = androidx.compose.ui.Alignment.CenterVertically),
    ) {
        Text(stringResource(R.string.home_title), style = MaterialTheme.typography.headlineMedium)
        Text(stringResource(R.string.home_subtitle), style = MaterialTheme.typography.bodyLarge)
        Text(stringResource(R.string.version_label, BuildConfig.VERSION_NAME))
        Text(stringResource(R.string.core_check, CoreInfo.label()))
        Button(onClick = onBench) { Text(stringResource(R.string.open_bench)) }
        Button(onClick = onDecode) { Text(stringResource(R.string.open_decode)) }
    }
}
