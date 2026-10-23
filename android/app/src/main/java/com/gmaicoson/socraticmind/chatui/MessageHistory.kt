package com.gmaicoson.socraticmind.chatui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.gmaicoson.socraticmind.chat.ChatActionsState
import com.gmaicoson.socraticmind.chat.ChatTurnState
import com.gmaicoson.socraticmind.chat.HistoryPageState
import com.gmaicoson.socraticmind.chat.StoredChatMessage
import com.gmaicoson.socraticmind.chat.markdown.MarkdownRenderer
import com.gmaicoson.socraticmind.messageui.MessageContent

@Composable
internal fun MessageHistory(
    page: HistoryPageState<StoredChatMessage>,
    refresh: () -> Unit,
    more: () -> Unit,
    renderer: MarkdownRenderer,
    turn: ChatTurnState,
    regenerationId: Long?,
    regenerate: () -> Unit,
    actions: ChatActionsState,
    toggleMessage: (Long) -> Unit,
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
            if (actions.selectionSessionId == message.sessionId) {
                Row {
                    Checkbox(
                        checked = message.id in actions.selectedIds,
                        onCheckedChange = { toggleMessage(message.id) },
                        enabled = turn.editable && !actions.busy,
                        modifier =
                            Modifier.testTag("chat_select_${message.id}").semantics {
                                contentDescription =
                                    "选择这条消息"
                            },
                    )
                    Text("选择这条消息")
                }
            }
            MessageContent(message, renderer)
            if (message.id == regenerationId && actions.selectionSessionId == null) {
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
