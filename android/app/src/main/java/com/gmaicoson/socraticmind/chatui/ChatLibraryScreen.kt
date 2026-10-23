package com.gmaicoson.socraticmind.chatui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.chat.ChatLibraryController
import com.gmaicoson.socraticmind.chat.ChatRegeneration
import com.gmaicoson.socraticmind.chat.ChatTurnController
import com.gmaicoson.socraticmind.chat.ChatTurnState
import com.gmaicoson.socraticmind.chat.ConversationSummary
import com.gmaicoson.socraticmind.chat.HistoryAccount
import com.gmaicoson.socraticmind.chat.HistoryLoad
import com.gmaicoson.socraticmind.chat.HistoryPageState
import com.gmaicoson.socraticmind.chat.StoredChatMessage
import com.gmaicoson.socraticmind.chat.markdown.MarkdownRenderer
import com.gmaicoson.socraticmind.messageui.MessageContent

@Composable
fun ChatLibraryScreen(
    model: ChatLibraryController,
    turn: ChatTurnController,
    account: SessionState.SignedIn,
    logout: () -> Unit,
    newConversation: () -> Unit,
    selectConversation: (String) -> Unit,
    closeConversation: () -> Unit,
) {
    val state by model.state.collectAsStateWithLifecycle()
    val turnState by turn.state.collectAsStateWithLifecycle()
    var discardDraft by remember { mutableStateOf(false) }
    val back = {
        if (turnState.editable) {
            if (turnState.draft.isNotEmpty()) discardDraft = true else closeConversation()
        }
    }
    val listState = rememberLazyListState()
    val renderer = remember(account.revision) { MarkdownRenderer() }
    DisposableEffect(renderer) { onDispose { renderer.clear() } }
    Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding()) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
            Text("你好，${account.user.username}", style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = logout) { Text("清理本机登录并退出") }
        }
        HorizontalDivider()
        // Session and feature flows can be delivered in different frames; never render a mismatched account.
        if (state.account != HistoryAccount.from(account) || turnState.account != state.account) {
            CircularProgressIndicator(Modifier.padding(24.dp))
        } else {
            val selected = state.selected
            BackHandler(enabled = selected != null, onBack = back)
            if (selected == null) {
                HistoryHeader("会话", state.conversations.loading, refresh = model::refreshConversations)
                TextButton(onClick = newConversation, enabled = turnState.editable) { Text("新建对话") }
                LazyColumn(state = listState, modifier = Modifier.weight(1f)) {
                    items(state.conversations.items, key = { "conversation:${it.sessionId}" }) { summary ->
                        ConversationRow(summary) { selectConversation(summary.sessionId) }
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
                    if (turnState.editable) back else null,
                    model::refreshMessages,
                )
                if (selected.target != turnState.target) {
                    CircularProgressIndicator(Modifier.padding(24.dp))
                } else {
                    key(selected.sessionId) {
                        MessageHistory(
                            state.messages,
                            model::refreshMessages,
                            model::loadMoreMessages,
                            renderer,
                            turnState,
                            ChatRegeneration.from(state)?.answerId,
                            { turn.regenerate(model.state.value, account.user.aiStyle) },
                            Modifier.weight(1f),
                        )
                    }
                }
            }
            ChatComposer(turnState, turn, account.user.aiStyle, selected != null && selected.target == turnState.target)
        }
    }
    if (discardDraft) {
        AlertDialog(
            onDismissRequest = { discardDraft = false },
            title = { Text("放弃未发送的内容？") },
            text = { Text("返回会话列表会清空当前草稿。") },
            confirmButton = {
                TextButton(onClick = {
                    discardDraft = false
                    closeConversation()
                }) { Text("放弃草稿") }
            },
            dismissButton = { TextButton(onClick = { discardDraft = false }) { Text("继续编辑") } },
        )
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
    renderer: MarkdownRenderer,
    turn: ChatTurnState,
    regenerationId: Long?,
    regenerate: () -> Unit,
    modifier: Modifier,
) {
    val scroll = rememberLazyListState()
    val visible = page.items.asReversed().filter(turn::showsInHistory)
    LaunchedEffect(page.loaded) {
        if (page.loaded && visible.isNotEmpty()) scroll.scrollToItem(visible.size)
    }
    LaunchedEffect(turn.pending?.requestId) {
        if (turn.pending != null) scroll.scrollToItem(visible.size + 1)
    }
    LazyColumn(modifier = modifier, state = scroll, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item(key = "message-controls") {
            HistoryPageControls(page, "暂无可读取的消息", "加载更早消息", refresh, more)
        }
        items(visible, key = { it.id }) { message ->
            MessageContent(message, renderer)
            if (message.id == regenerationId) {
                TextButton(
                    onClick = regenerate,
                    enabled = turn.canRegenerate,
                    modifier = Modifier.testTag("chat_regenerate"),
                ) {
                    Text("重新生成回答")
                }
            }
        }
        if (turn.pending != null) {
            item(key = "pending-turn") {
                if (turn.pending?.regenerateMessageId != null) {
                    Text("正在重新生成，完成前保留原回答。")
                } else if (turn.submitted.isNotEmpty()) {
                    MessageContent("user", turn.submitted, renderer)
                }
                MessageContent("ai", turn.partial, renderer, provisional = true)
            }
        }
    }
}
