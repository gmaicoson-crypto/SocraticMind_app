package com.gmaicoson.socraticmind.messageui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gmaicoson.socraticmind.chat.markdown.MarkdownAlignment
import com.gmaicoson.socraticmind.chat.markdown.MarkdownBlock
import com.gmaicoson.socraticmind.chat.markdown.MarkdownContent
import com.gmaicoson.socraticmind.chat.markdown.MarkdownTable

@Composable
internal fun MarkdownBlockView(
    block: MarkdownBlock,
    openLink: (String) -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().padding(start = (minOf(block.indent, 6) * 12).dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (block.quoteDepth >
            0
        ) {
            Text("│".repeat(minOf(block.quoteDepth, 3)), color = MaterialTheme.colorScheme.outline)
        }
        block.marker?.let { Text(it, style = MaterialTheme.typography.bodyLarge) }
        Column(Modifier.weight(1f)) {
            when (val content = block.content) {
                is MarkdownContent.Text -> MarkdownInline(content.runs, openLink, level = content.heading)
                is MarkdownContent.Code -> MarkdownCode(content)
                is MarkdownContent.Table -> MarkdownTableView(content.value, openLink)
                MarkdownContent.Rule -> HorizontalDivider(Modifier.padding(vertical = 8.dp))
            }
        }
    }
}

@Composable
private fun MarkdownCode(code: MarkdownContent.Code) {
    Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainer).padding(12.dp)) {
        Row(Modifier.fillMaxWidth()) {
            Text(
                code.language.ifEmpty { "代码" },
                Modifier.weight(1f).padding(vertical = 12.dp),
                style = MaterialTheme.typography.labelMedium,
            )
            MessageCopyButton(code.text, "复制代码")
        }
        SelectionContainer {
            Text(
                code.text,
                Modifier
                    .heightIn(max = 300.dp)
                    .verticalScroll(rememberScrollState())
                    .horizontalScroll(rememberScrollState()),
                style = MaterialTheme.typography.bodyMedium,
                fontFamily = FontFamily.Monospace,
                softWrap = false,
            )
        }
    }
}

@Composable
private fun MarkdownTableView(
    table: MarkdownTable,
    openLink: (String) -> Unit,
) {
    var visibleRows by remember(table) { mutableIntStateOf(21) }
    Column {
        Column(Modifier.horizontalScroll(rememberScrollState())) {
            table.rows.take(visibleRows).forEachIndexed { rowIndex, row ->
                Row(
                    Modifier.background(
                        if (rowIndex == 0) {
                            MaterialTheme.colorScheme.surfaceContainerHigh
                        } else {
                            MaterialTheme.colorScheme.surface
                        },
                    ),
                ) {
                    row.forEachIndexed { columnIndex, runs ->
                        val alignment =
                            when (table.alignments.getOrNull(columnIndex)) {
                                MarkdownAlignment.CENTER -> TextAlign.Center
                                MarkdownAlignment.RIGHT -> TextAlign.End
                                else -> TextAlign.Start
                            }
                        MarkdownInline(
                            runs,
                            openLink,
                            Modifier.width(180.dp).padding(8.dp),
                            bold = rowIndex == 0,
                            alignment = alignment,
                        )
                    }
                }
                HorizontalDivider()
            }
        }
        if (visibleRows < table.rows.size) {
            TextButton(onClick = { visibleRows += 20 }) { Text("显示更多表格行（剩余 ${table.rows.size - visibleRows}）") }
        }
    }
}
