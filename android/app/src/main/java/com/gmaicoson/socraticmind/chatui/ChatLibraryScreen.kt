package com.gmaicoson.socraticmind.chatui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.chat.ChatLibraryController
import com.gmaicoson.socraticmind.chat.ConversationSummary
import com.gmaicoson.socraticmind.chat.HistoryAccount
import com.gmaicoson.socraticmind.chat.HistoryLoad
import com.gmaicoson.socraticmind.chat.HistoryPageState
import com.gmaicoson.socraticmind.chat.StoredChatMessage

@Composable
fun ChatLibraryScreen(
    model: ChatLibraryController,
    account: SessionState.SignedIn,
    logout: () -> Unit,
) {
    val state by model.state.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()
    Column(Modifier.fillMaxSize().safeDrawingPadding()) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
            Text("你好，${account.user.username}", style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = logout) { Text("清理本机登录并退出") }
        }
        HorizontalDivider()
        // Session and feature flows can be delivered in different frames; never render a mismatched account.
        if (state.account != HistoryAccount.from(account)) {
            CircularProgressIndicator(Modifier.padding(24.dp))
        } else {
            val selected = state.selected
            BackHandler(enabled = selected != null, onBack = model::closeConversation)
            if (selected == null) {
                HistoryHeader("会话", state.conversations.loading, refresh = model::refreshConversations)
                LazyColumn(state = listState, modifier = Modifier.weight(1f)) {
                    items(state.conversations.items, key = { "conversation:${it.sessionId}" }) { summary ->
                        ConversationRow(summary) { model.selectConversation(summary.sessionId) }
                    }
                    item(key = "conversation-controls") {
                        HistoryPageControls(
                            state.conversations,
                            "暂无历史会话",
                            "加载更多会话",
                            model::refreshConversations,
                            model::loadMoreConversations,
                        )
                    }
                }
            } else {
                HistoryHeader(
                    selected.title?.takeIf { it.isNotBlank() } ?: "对话",
                    state.messages.loading,
                    model::closeConversation,
                    model::refreshMessages,
                )
                key(selected.sessionId) {
                    MessageHistory(state.messages, model::refreshMessages, model::loadMoreMessages, Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun HistoryHeader(
    title: String,
    loading: HistoryLoad?,
    back: (() -> Unit)? = null,
    refresh: () -> Unit,
) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        back?.let { TextButton(onClick = it) { Text("返回") } }
        Text(
            title,
            Modifier.weight(1f).padding(vertical = 12.dp).semantics { heading() },
            style = MaterialTheme.typography.titleLarge,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        TextButton(onClick = refresh, enabled = loading != HistoryLoad.REFRESH) { Text("刷新") }
    }
}

@Composable
private fun ConversationRow(
    summary: ConversationSummary,
    select: () -> Unit,
) {
    Column(
        Modifier.fillMaxWidth().clickable(onClick = select).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            summary.title?.takeIf { it.isNotBlank() } ?: "未命名对话",
            style = MaterialTheme.typography.titleMedium,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            summary.preview.ifBlank { "暂无文字预览" },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
    HorizontalDivider()
}

@Composable
private fun MessageHistory(
    page: HistoryPageState<StoredChatMessage>,
    refresh: () -> Unit,
    more: () -> Unit,
    modifier: Modifier,
) {
    val scroll = rememberLazyListState()
    LaunchedEffect(page.loaded) {
        if (page.loaded && page.items.isNotEmpty()) scroll.scrollToItem(page.items.size)
    }
    LazyColumn(modifier = modifier, state = scroll, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item(key = "message-controls") {
            HistoryPageControls(page, "暂无可读取的消息", "加载更早消息", refresh, more)
        }
        items(page.items.asReversed(), key = { it.id }) { message ->
            Column(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    if (message.role == "user") "你" else "SocraticMind",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary,
                )
                SelectionContainer { Text(message.content, style = MaterialTheme.typography.bodyLarge) }
                if (message.attachments.isNotEmpty()) {
                    Text("包含 ${message.attachments.size} 个附件", style = MaterialTheme.typography.labelMedium)
                }
            }
        }
    }
}
