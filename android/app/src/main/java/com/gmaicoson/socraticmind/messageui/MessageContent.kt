package com.gmaicoson.socraticmind.messageui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.gmaicoson.socraticmind.avatarui.AvatarImage
import com.gmaicoson.socraticmind.avatarui.AvatarPresentation
import com.gmaicoson.socraticmind.chat.StoredChatMessage
import com.gmaicoson.socraticmind.chat.markdown.MarkdownDocument
import com.gmaicoson.socraticmind.chat.markdown.MarkdownLink
import com.gmaicoson.socraticmind.chat.markdown.MarkdownRenderer
import kotlinx.coroutines.CancellationException

@Composable
fun MessageContent(
    message: StoredChatMessage,
    renderer: MarkdownRenderer,
    avatar: AvatarPresentation? = null,
) = MessageContent(message.role, message.content, renderer, attachments = message.attachments.size, avatar = avatar)

@Composable
fun MessageContent(
    role: String,
    content: String,
    renderer: MarkdownRenderer,
    provisional: Boolean = false,
    attachments: Int = 0,
    avatar: AvatarPresentation? = null,
) {
    Column(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (role != "user" && avatar != null) AvatarImage(avatar, 32.dp)
            Text(
                if (role == "user") "你" else "SocraticMind",
                Modifier.weight(1f).padding(vertical = 12.dp),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
            )
            MessageCopyButton(content, if (provisional) "复制当前文字" else "复制原文")
        }
        if (provisional) {
            Text(content.ifEmpty { "正在等待回复…" }, maxLines = 32, overflow = TextOverflow.Ellipsis)
        } else {
            MarkdownBody(content, renderer)
        }
        if (attachments > 0) {
            Text("包含 $attachments 个附件", style = MaterialTheme.typography.labelMedium)
        }
    }
}

private data class RenderedMarkdown(
    val source: String,
    val document: MarkdownDocument?,
)

@Composable
private fun MarkdownBody(
    source: String,
    renderer: MarkdownRenderer,
) {
    val rendered by produceState<RenderedMarkdown?>(null, source, renderer) {
        value = null
        try {
            value = RenderedMarkdown(source, renderer.render(source))
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            value = RenderedMarkdown(source, null)
        }
    }
    // produceState can retain a previous value until its effect runs; check the source before displaying it.
    val current = rendered?.takeIf { it.source == source }
    if (current == null) {
        Text("正在排版…", color = MaterialTheme.colorScheme.onSurfaceVariant)
    } else if (current.document == null) {
        Text("暂时无法显示消息，仍可复制原文。", color = MaterialTheme.colorScheme.error)
    } else {
        key(source) { MarkdownDocumentView(current.document) }
    }
}

@Composable
private fun MarkdownDocumentView(document: MarkdownDocument) {
    var visibleBlocks by remember { mutableIntStateOf(24) }
    var linkError by remember { mutableStateOf(false) }
    val handler = LocalUriHandler.current
    val openLink: (String) -> Unit = { raw ->
        val safe = MarkdownLink.safe(raw)
        linkError =
            if (safe == null) {
                true
            } else {
                try {
                    handler.openUri(safe)
                    false
                } catch (_: Exception) {
                    true
                }
            }
    }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (document.plainFallback) Text("此消息按原文分段显示。", style = MaterialTheme.typography.labelMedium)
        document.blocks.take(visibleBlocks).forEach { MarkdownBlockView(it, openLink) }
        if (visibleBlocks < document.blocks.size) {
            TextButton(
                onClick = { visibleBlocks += 24 },
            ) { Text("显示更多内容（剩余 ${document.blocks.size - visibleBlocks} 段）") }
        }
        if (linkError) Text("无法打开这个链接。", color = MaterialTheme.colorScheme.error)
    }
}
