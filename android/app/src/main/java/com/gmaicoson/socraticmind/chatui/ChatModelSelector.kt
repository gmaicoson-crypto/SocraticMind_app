package com.gmaicoson.socraticmind.chatui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.gmaicoson.socraticmind.chat.ChatModelController
import com.gmaicoson.socraticmind.chat.ChatModelSource
import com.gmaicoson.socraticmind.chat.ChatTurnState
import com.gmaicoson.socraticmind.chat.HistoryAccount

@Composable
fun ChatModelSelector(
    model: ChatModelController,
    turn: ChatTurnState,
    account: HistoryAccount,
) {
    val state by model.state.collectAsStateWithLifecycle()
    if (state.account != account || turn.account != account) return
    var expanded by remember(account) { mutableStateOf(false) }
    val enabled = turn.editable && turn.receipt == null
    LaunchedEffect(enabled) { if (!enabled) expanded = false }
    Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp)) {
        Row {
            TextButton(
                onClick = { expanded = true },
                enabled = enabled,
                modifier = Modifier.weight(1f).testTag("model-selector"),
            ) {
                Text("模型：${state.label}", maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            TextButton(
                onClick = model::refresh,
                enabled = !state.loading,
                modifier = Modifier.testTag("model-refresh"),
            ) {
                Text(if (state.loading) "刷新中…" else "刷新模型")
            }
        }
        if (!state.available) Text("所选模型已不在目录中，请重新选择后发送。", color = MaterialTheme.colorScheme.error)
        state.notice?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    }
    if (expanded) {
        AlertDialog(
            onDismissRequest = { expanded = false },
            title = { Text("选择模型") },
            text = {
                LazyColumn(Modifier.fillMaxWidth().heightIn(max = 360.dp)) {
                    item(key = "disclosure") {
                        Text(
                            "提问、相关对话和附件会经后端发送给所选模型。目录只表示已配置，不代表调用可用或免费。",
                            Modifier.padding(bottom = 12.dp),
                        )
                    }
                    item(key = "default") {
                        ModelChoiceRow("服务端默认", "使用后端配置的默认模型", state.selectedId == null) {
                            model.select(null, account)
                            expanded = false
                        }
                    }
                    for (source in ChatModelSource.entries) {
                        val options =
                            state.catalog
                                ?.models
                                .orEmpty()
                                .filter { it.source == source }
                        if (options.isNotEmpty()) {
                            item(key = source.wireValue) {
                                Text(
                                    if (source == ChatModelSource.ENVIRONMENT) "系统模型" else "我的模型",
                                    Modifier.padding(top = 12.dp),
                                    style = MaterialTheme.typography.titleSmall,
                                )
                            }
                            items(options, key = { "model:${it.id}" }) { option ->
                                ModelChoiceRow(option.name, option.model, state.selectedId == option.id) {
                                    model.select(option.id, account)
                                    expanded = false
                                }
                            }
                        }
                    }
                    if (state.catalog?.models?.isEmpty() == true) {
                        item(key = "empty") { Text("暂无可选模型。可稍后刷新，或尝试服务端默认。") }
                    }
                    if (state.loading) item(key = "loading") { Text("正在读取模型目录…") }
                }
            },
            confirmButton = { TextButton(onClick = { expanded = false }) { Text("关闭") } },
        )
    }
}

@Composable
private fun ModelChoiceRow(
    title: String,
    detail: String,
    selected: Boolean,
    choose: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .selectable(
                selected = selected,
                role = Role.RadioButton,
                onClick = choose,
            ).padding(8.dp),
    ) {
        RadioButton(selected = selected, onClick = null)
        Column(Modifier.padding(start = 8.dp)) {
            Text(title)
            Text(detail, style = MaterialTheme.typography.bodySmall)
        }
    }
}
