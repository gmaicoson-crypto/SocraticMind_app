package com.gmaicoson.socraticmind.messageui

import android.content.ClipData
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable
internal fun MessageCopyButton(
    text: String,
    label: String,
) {
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    var feedback by remember(text) { mutableStateOf<String?>(null) }
    TextButton(onClick = {
        scope.launch {
            try {
                clipboard.setClipEntry(ClipEntry(ClipData.newPlainText(label, text)))
                feedback = "已复制"
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                feedback = "复制失败，请重试"
            }
        }
    }) { Text(feedback ?: label) }
}
