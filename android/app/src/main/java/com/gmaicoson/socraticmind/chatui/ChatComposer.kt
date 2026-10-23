package com.gmaicoson.socraticmind.chatui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.gmaicoson.socraticmind.chat.ChatTurnController
import com.gmaicoson.socraticmind.chat.ChatTurnPhase
import com.gmaicoson.socraticmind.chat.ChatTurnState

@Composable
fun ChatComposer(
    state: ChatTurnState,
    model: ChatTurnController,
    style: String,
    selected: Boolean,
) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        val status =
            state.notice ?: when (state.phase) {
                ChatTurnPhase.RESTORING -> "正在核对上次请求…"
                ChatTurnPhase.PREPARING -> "正在准备发送…"
                ChatTurnPhase.SENDING -> "正在回复，显示内容尚未确认。"
                else -> null
            }
        status?.let { Text(it, Modifier.testTag("chat_status"), style = MaterialTheme.typography.bodySmall) }
        if (selected) {
            OutlinedTextField(
                value = state.draft,
                onValueChange = model::edit,
                label = { Text("输入消息") },
                enabled = state.editable,
                minLines = 1,
                maxLines = 5,
                isError = state.characterCount > 5000,
                supportingText = { Text("${state.characterCount} / 5000") },
                modifier = Modifier.fillMaxWidth().testTag("chat_input"),
            )
        }
        Row(Modifier.fillMaxWidth()) {
            if (state.canVerify) {
                TextButton(onClick = model::verify, modifier = Modifier.testTag("chat_verify")) { Text("核对状态") }
            }
            if (state.canStop) {
                TextButton(onClick = model::stop, modifier = Modifier.testTag("chat_stop")) { Text("停止回复") }
            }
            if (selected) {
                Button(
                    onClick = { model.send(style) },
                    enabled = state.canSend,
                    modifier = Modifier.testTag("chat_send"),
                ) { Text("发送") }
            }
        }
    }
}
