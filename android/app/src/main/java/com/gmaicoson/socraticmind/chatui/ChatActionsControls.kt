package com.gmaicoson.socraticmind.chatui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import com.gmaicoson.socraticmind.chat.ChatAction
import com.gmaicoson.socraticmind.chat.ChatActionsController
import com.gmaicoson.socraticmind.chat.ChatActionsState

@Composable
internal fun ChatManagementMenu(
    sessionId: String,
    enabled: Boolean,
    model: ChatActionsController,
    messages: Boolean = false,
) {
    var expanded by remember(sessionId) { mutableStateOf(false) }
    Box {
        TextButton(onClick = { expanded = true }, enabled = enabled) { Text("管理会话") }
        DropdownMenu(expanded = expanded && enabled, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(text = { Text("重命名") }, onClick = {
                expanded = false
                model.rename(sessionId)
            })
            DropdownMenuItem(text = { Text("删除整个会话") }, onClick = {
                expanded = false
                model.deleteSession(sessionId)
            })
            if (messages) {
                DropdownMenuItem(text = { Text("选择消息") }, onClick = {
                    expanded = false
                    model.selectMessages()
                })
            }
        }
    }
}

@Composable
internal fun ChatSelectionControls(
    state: ChatActionsState,
    enabled: Boolean,
    model: ChatActionsController,
) {
    Column {
        Text("已选择 ${state.selectedIds.size} 条消息（最多 100 条）")
        Row {
            TextButton(onClick = model::deleteSelectedMessages, enabled = enabled && state.selectedIds.isNotEmpty()) {
                Text("删除所选")
            }
            TextButton(onClick = model::dismiss, enabled = !state.busy) { Text("结束选择") }
        }
    }
}

@Composable
internal fun ChatActionDialog(
    state: ChatActionsState,
    model: ChatActionsController,
) {
    val dialog = state.dialog ?: return
    val renaming = dialog is ChatAction.Rename
    AlertDialog(
        onDismissRequest = model::cancelDialog,
        title = { Text(if (renaming) "重命名会话" else "确认删除") },
        text = {
            Column {
                when (dialog) {
                    is ChatAction.Rename -> {
                        OutlinedTextField(
                            value = dialog.title,
                            onValueChange = model::editTitle,
                            label = { Text("会话标题") },
                            singleLine = true,
                            enabled = !state.busy,
                            modifier = Modifier.testTag("chat_title_input"),
                        )
                        val title = dialog.title.trim()
                        Text("${title.codePointCount(0, title.length)} / 40 字")
                    }

                    is ChatAction.DeleteSession -> {
                        Text("删除“${dialog.title.ifBlank { "未命名对话" }}”及其消息？此操作无法撤销。")
                        if (dialog.discardsDraft) Text("当前未发送的草稿也会清空。")
                    }

                    is ChatAction.DeleteMessages -> {
                        Text("删除所选 ${dialog.ids.size} 条消息？此操作无法撤销。")
                    }
                }
                state.notice?.let { Text(it) }
                if (state.busy) CircularProgressIndicator()
            }
        },
        confirmButton = {
            TextButton(
                onClick = model::confirm,
                enabled = state.canConfirm,
                modifier = Modifier.testTag("chat_action_confirm"),
            ) {
                Text(if (renaming) "保存" else "删除")
            }
        },
        dismissButton = { TextButton(onClick = model::cancelDialog, enabled = !state.busy) { Text("取消") } },
    )
}
