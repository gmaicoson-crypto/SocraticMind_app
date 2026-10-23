package com.gmaicoson.socraticmind.chatui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.gmaicoson.socraticmind.chat.ChatSuggestionsController
import com.gmaicoson.socraticmind.chat.ChatTarget
import com.gmaicoson.socraticmind.chat.HistoryAccount
import com.gmaicoson.socraticmind.chat.SuggestionSource

@Composable
fun ChatSuggestionsBar(
    model: ChatSuggestionsController,
    account: HistoryAccount,
    target: ChatTarget,
    style: String,
) {
    val state by model.state.collectAsStateWithLifecycle()
    val context = state.context ?: return
    if (context.account != account || context.target != target) return
    Column(Modifier.padding(horizontal = 12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(
                if (state.source ==
                    SuggestionSource.AI
                ) {
                    "AI 建议"
                } else {
                    "参考话题"
                },
                style = MaterialTheme.typography.labelMedium,
            )
            TextButton(onClick = model::refresh, enabled = state.enabled && !state.loading && state.choice == null) {
                Text(if (state.loading) "正在获取…" else "换一批")
            }
        }
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.items, key = { it }) { text ->
                TextButton(
                    onClick = { model.choose(text, context, style) },
                    enabled = state.enabled,
                    modifier = Modifier.widthIn(max = 260.dp).semantics { contentDescription = "发送建议：$text" },
                ) {
                    Text(text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
        }
        state.notice?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    }
    state.choice?.let { choice ->
        AlertDialog(
            onDismissRequest = model::cancelChoice,
            title = { Text("替换草稿并发送？") },
            text = { Text(choice.text, maxLines = 6, overflow = TextOverflow.Ellipsis) },
            confirmButton = { TextButton(onClick = { model.confirmChoice(style) }) { Text("替换并发送") } },
            dismissButton = { TextButton(onClick = model::cancelChoice) { Text("保留草稿") } },
        )
    }
}
