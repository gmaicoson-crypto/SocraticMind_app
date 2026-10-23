package com.gmaicoson.socraticmind.chat.markdown

import org.commonmark.ext.gfm.strikethrough.StrikethroughExtension
import org.commonmark.ext.gfm.tables.TableBlock
import org.commonmark.ext.gfm.tables.TableCell
import org.commonmark.ext.gfm.tables.TablesExtension
import org.commonmark.ext.task.list.items.TaskListItemMarker
import org.commonmark.ext.task.list.items.TaskListItemsExtension
import org.commonmark.node.BlockQuote
import org.commonmark.node.BulletList
import org.commonmark.node.FencedCodeBlock
import org.commonmark.node.Heading
import org.commonmark.node.HtmlBlock
import org.commonmark.node.IndentedCodeBlock
import org.commonmark.node.Node
import org.commonmark.node.OrderedList
import org.commonmark.node.Paragraph
import org.commonmark.node.ThematicBreak
import org.commonmark.parser.Parser

/** Pure projection. Call via MarkdownRenderer so parsing never runs on the UI thread. */
object MarkdownParser {
    fun parse(source: String): MarkdownDocument {
        if (!MarkdownBudget.accepts(source)) return plainMarkdown(source)
        return try {
            val parser =
                Parser
                    .builder()
                    .extensions(
                        listOf(
                            TablesExtension.builder().maxCells(2048).build(),
                            StrikethroughExtension.create(),
                            TaskListItemsExtension.create(),
                        ),
                    ).maxOpenBlockParsers(64)
                    .maxInlineNesting(64)
                    .build()
            MarkdownBlockProjection().document(parser.parse(source))
        } catch (_: MarkdownLimit) {
            plainMarkdown(source)
        } catch (_: IllegalArgumentException) {
            plainMarkdown(source)
        }
    }
}

private class MarkdownBlockProjection {
    private val budget = MarkdownBudget()
    private val inline = MarkdownInlineProjection(budget)
    private val blocks = mutableListOf<MarkdownBlock>()

    fun document(root: Node): MarkdownDocument {
        root.children().forEach { visit(it, 0, 0, 0) }
        return MarkdownDocument(blocks.toList())
    }

    private fun visit(
        node: Node,
        quote: Int,
        indent: Int,
        depth: Int,
    ) {
        budget.visit(depth)
        when (node) {
            is Paragraph -> {
                add(MarkdownContent.Text(inline.runs(node)), quote, indent)
            }

            is Heading -> {
                add(MarkdownContent.Text(inline.runs(node), node.level), quote, indent)
            }

            is FencedCodeBlock -> {
                code(node.literal, node.info.orEmpty(), quote, indent)
            }

            is IndentedCodeBlock -> {
                code(node.literal, "", quote, indent)
            }

            is HtmlBlock -> {
                // cmark includes the final block newline; Java CommonMark omits it.
                val literal = node.literal.removeSuffix("\n") + "\n"
                budget.literal(literal)
                add(MarkdownContent.Text(listOf(MarkdownRun(literal))), quote, indent)
            }

            is ThematicBreak -> {
                add(MarkdownContent.Rule, quote, indent)
            }

            is BlockQuote -> {
                node.children().forEach { visit(it, quote + 1, indent, depth + 1) }
            }

            is BulletList, is OrderedList -> {
                list(node, quote, indent, depth)
            }

            is TableBlock -> {
                table(node, quote, indent)
            }

            else -> {
                node.children().forEach { visit(it, quote, indent, depth + 1) }
            }
        }
    }

    private fun list(
        node: Node,
        quote: Int,
        indent: Int,
        depth: Int,
    ) {
        var number = (node as? OrderedList)?.markerStartNumber ?: 1
        node.children().forEach { item ->
            budget.visit(depth + 1)
            val first = blocks.size
            val task = item.firstChild as? TaskListItemMarker
            val marker =
                when {
                    task != null -> if (task.isChecked) "☑" else "☐"
                    node is OrderedList -> "${number++}."
                    else -> "•"
                }
            item.children().forEach { visit(it, quote, indent + 1, depth + 2) }
            if (blocks.size == first) add(MarkdownContent.Text(emptyList()), quote, indent + 1)
            if (blocks[first].marker != null) {
                if (blocks.size >= 512) throw MarkdownLimit()
                blocks.add(first, MarkdownBlock(MarkdownContent.Text(emptyList()), quote, indent + 1))
            }
            blocks[first] = blocks[first].copy(marker = marker)
        }
    }

    private fun code(
        text: String,
        info: String,
        quote: Int,
        indent: Int,
    ) {
        budget.literal(text)
        val language = info.trim().takeWhile { !it.isWhitespace() }.take(64)
        add(MarkdownContent.Code(text, language), quote, indent)
    }

    private fun table(
        node: Node,
        quote: Int,
        indent: Int,
    ) {
        val rows = node.children().flatMap { it.children() }.toList()
        val cells = rows.map { row -> row.children().filterIsInstance<TableCell>().toList() }
        if (cells.sumOf { it.size } > 2048 || cells.any { it.size > 32 }) throw MarkdownLimit()
        val alignments =
            cells.firstOrNull().orEmpty().map {
                when (it.alignment) {
                    TableCell.Alignment.CENTER -> MarkdownAlignment.CENTER
                    TableCell.Alignment.RIGHT -> MarkdownAlignment.RIGHT
                    else -> MarkdownAlignment.LEFT
                }
            }
        val projected =
            cells.map { row ->
                row.map {
                    budget.visit(0)
                    inline.runs(it)
                }
            }
        add(MarkdownContent.Table(MarkdownTable(alignments, projected)), quote, indent)
    }

    private fun add(
        content: MarkdownContent,
        quote: Int,
        indent: Int,
    ) {
        if (blocks.size >= 512) throw MarkdownLimit()
        blocks.add(MarkdownBlock(content, quote, indent))
    }
}
