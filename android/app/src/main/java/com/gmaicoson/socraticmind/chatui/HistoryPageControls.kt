package com.gmaicoson.socraticmind.chatui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gmaicoson.socraticmind.chat.HistoryLoad
import com.gmaicoson.socraticmind.chat.HistoryPageState

@Composable
internal fun <T> HistoryPageControls(
    page: HistoryPageState<T>,
    emptyText: String,
    moreText: String,
    refresh: () -> Unit,
    more: () -> Unit,
) {
    val failure = page.failure
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (page.loading != null) {
            CircularProgressIndicator()
            Text(if (page.loading == HistoryLoad.MORE) "正在读取更多…" else "正在刷新…")
        } else if (failure != null) {
            Text(failure.message, color = MaterialTheme.colorScheme.error)
            TextButton(onClick = if (failure.operation == HistoryLoad.MORE) more else refresh) { Text("重试") }
        } else if (page.loaded && page.items.isEmpty()) {
            Text(emptyText, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else if (page.nextCursor != null) {
            TextButton(onClick = more) { Text(moreText) }
        }
    }
}
