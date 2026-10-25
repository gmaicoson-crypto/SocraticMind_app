package com.gmaicoson.socraticmind.messageui

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import com.gmaicoson.socraticmind.chat.ChatAnswerFeedback

/** Shared by ordinary and node messages; usage is optional detail, failure remains visible. */
@Composable
internal fun MessageFeedback(feedback: ChatAnswerFeedback) {
    var expanded by remember(feedback) { mutableStateOf(false) }
    Column {
        feedback.failure?.let {
            Text(it.message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        TextButton(onClick = { expanded = !expanded }, modifier = Modifier.testTag("chat_usage")) {
            Text(if (expanded) "收起模型用量" else "模型用量")
        }
        if (expanded) {
            Text(feedback.usageSummary, style = MaterialTheme.typography.bodySmall)
            Text(ChatAnswerFeedback.SCOPE_NOTE, style = MaterialTheme.typography.bodySmall)
        }
    }
}
