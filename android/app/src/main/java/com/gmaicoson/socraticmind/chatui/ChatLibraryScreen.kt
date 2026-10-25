package com.gmaicoson.socraticmind.chatui

import android.graphics.Bitmap
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.avatarui.AvatarImage
import com.gmaicoson.socraticmind.avatarui.AvatarPresentation
import com.gmaicoson.socraticmind.avatarui.ChatAvatarControls
import com.gmaicoson.socraticmind.avatarui.ChatAvatarPickerDialog
import com.gmaicoson.socraticmind.chat.ChatActionsController
import com.gmaicoson.socraticmind.chat.ChatAvatarController
import com.gmaicoson.socraticmind.chat.ChatAvatarResource
import com.gmaicoson.socraticmind.chat.ChatLibraryController
import com.gmaicoson.socraticmind.chat.ChatMode
import com.gmaicoson.socraticmind.chat.ChatRegeneration
import com.gmaicoson.socraticmind.chat.ChatSuggestionsController
import com.gmaicoson.socraticmind.chat.ChatTurnController
import com.gmaicoson.socraticmind.chat.ConversationSummary
import com.gmaicoson.socraticmind.chat.HistoryAccount
import com.gmaicoson.socraticmind.chat.HistoryLoad
import com.gmaicoson.socraticmind.chat.images.AvatarImageLoader
import com.gmaicoson.socraticmind.chat.markdown.MarkdownRenderer

@Composable
fun ChatLibraryScreen(
    model: ChatLibraryController,
    turn: ChatTurnController,
    actions: ChatActionsController,
    suggestions: ChatSuggestionsController,
    avatars: ChatAvatarController,
    avatarImages: AvatarImageLoader<Bitmap>?,
    account: SessionState.SignedIn,
    logout: () -> Unit,
    newConversation: () -> Unit,
    selectConversation: (String) -> Unit,
    closeConversation: () -> Unit,
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(model, suggestions, lifecycleOwner) {
        val lifecycle = lifecycleOwner.lifecycle
        val observer =
            LifecycleEventObserver { _, _ ->
                model.setTitlePollingActive(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
                suggestions.setActive(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
            }
        lifecycle.addObserver(observer)
        model.setTitlePollingActive(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
        suggestions.setActive(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
        onDispose {
            lifecycle.removeObserver(observer)
            model.setTitlePollingActive(false)
            suggestions.setActive(false)
        }
    }
    val state by model.state.collectAsStateWithLifecycle()
    val turnState by turn.state.collectAsStateWithLifecycle()
    val actionState by actions.state.collectAsStateWithLifecycle()
    val avatarState by avatars.state.collectAsStateWithLifecycle()
    var discardDraft by remember { mutableStateOf(false) }
    val back = {
        if (turnState.editable) {
            if (actionState.selectionSessionId != null) {
                actions.dismiss()
            } else if (turnState.draft.isNotEmpty()) {
                discardDraft = true
            } else {
                closeConversation()
            }
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
        if (state.account != HistoryAccount.from(account) || turnState.account != state.account ||
            actionState.account != state.account || avatarState.account != state.account
        ) {
            CircularProgressIndicator(Modifier.padding(24.dp))
        } else {
            state.titleNotice?.let { Text(it, Modifier.padding(horizontal = 12.dp)) }
            val selected = state.selected
            BackHandler(enabled = selected != null, onBack = back)
            if (selected == null) {
                HistoryHeader("会话", state.conversations.loading, refresh = model::refreshConversations)
                TextButton(onClick = newConversation, enabled = turnState.editable) { Text("新建对话") }
                LazyColumn(state = listState, modifier = Modifier.weight(1f)) {
                    items(state.conversations.items, key = { "conversation:${it.sessionId}" }) { summary ->
                        val mode = ChatMode.entries.find { it.wireValue == summary.mode } ?: ChatMode.NORMAL
                        ConversationRow(
                            summary,
                            turnState.editable,
                            actions,
                            AvatarPresentation(
                                avatarImages,
                                avatarState.resource(summary.sessionId, mode),
                                ChatAvatarResource.default(mode),
                            ),
                        ) { selectConversation(summary.sessionId) }
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
                    model::refreshSelectedConversation,
                )
                ChatAvatarControls(
                    avatars,
                    avatarState,
                    avatarImages,
                    selected.target,
                    turnState.editable && actionState.dialog == null && actionState.selectionSessionId == null,
                )
                if (actionState.selectionSessionId == selected.sessionId) {
                    ChatSelectionControls(actionState, turnState.editable && !actionState.busy, actions)
                } else {
                    ChatManagementMenu(
                        selected.sessionId,
                        actions.canManage(selected.sessionId),
                        actions,
                        messages = state.messages.items.isNotEmpty(),
                    )
                }
                if (selected.target != turnState.target) {
                    CircularProgressIndicator(Modifier.padding(24.dp))
                } else {
                    key(selected.sessionId) {
                        MessageHistory(
                            state.messages,
                            model::refreshSelectedConversation,
                            model::loadMoreMessages,
                            renderer,
                            turnState,
                            ChatRegeneration.from(state)?.answerId,
                            { turn.regenerate(model.state.value, account.user.aiStyle) },
                            actionState,
                            actions::toggleMessage,
                            AvatarPresentation(
                                avatarImages,
                                avatarState.resource(selected.target),
                                ChatAvatarResource.default(selected.target.mode),
                            ),
                            Modifier.weight(1f),
                        )
                    }
                }
            }
            if (selected == null) ChatAvatarControls(avatars, avatarState, avatarImages, null, turnState.editable)
            if (actionState.dialog == null) actionState.notice?.let { Text(it, Modifier.padding(12.dp)) }
            if (actionState.selectionSessionId == null) {
                if (actionState.dialog == null && selected != null && selected.target == turnState.target) {
                    ChatSuggestionsBar(suggestions, checkNotNull(state.account), selected.target, account.user.aiStyle)
                }
                ChatComposer(
                    turnState,
                    turn,
                    account.user.aiStyle,
                    selected != null && selected.target == turnState.target,
                )
            }
        }
    }
    if (actionState.account == HistoryAccount.from(account)) ChatActionDialog(actionState, actions)
    avatarState.picker?.takeIf { it.account == HistoryAccount.from(account) }?.let { picker ->
        key(picker.id) { ChatAvatarPickerDialog(avatars, avatarState, picker, avatarImages, turnState.editable) }
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
    enabled: Boolean,
    actions: ChatActionsController,
    avatar: AvatarPresentation,
    select: () -> Unit,
) {
    Column(
        Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = select).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            AvatarImage(avatar)
            Text(
                summary.title?.takeIf { it.isNotBlank() } ?: "未命名对话",
                style = MaterialTheme.typography.titleMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            summary.preview.ifBlank { "暂无文字预览" },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        ChatManagementMenu(summary.sessionId, actions.canManage(summary.sessionId), actions)
    }
    HorizontalDivider()
}
