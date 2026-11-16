package com.takipli.oynat

import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp

/**
 * Frame preview that never takes more than ~55 % of the window height, centred. On a wide window (unfolded foldable, tablet) a
 * full-width preview is taller than the screen and leaves no room to scroll to the settings and the start button.
 */
@Composable
fun previewModifier(aspect: Float): Modifier {
    val h = LocalConfiguration.current.screenHeightDp
    val maxW = (h * 0.55f * aspect).dp
    return Modifier.fillMaxWidth().wrapContentWidth(Alignment.CenterHorizontally).widthIn(max = maxW).fillMaxWidth().aspectRatio(aspect)
}
