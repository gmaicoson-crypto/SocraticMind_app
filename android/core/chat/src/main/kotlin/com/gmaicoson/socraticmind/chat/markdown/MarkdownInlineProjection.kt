package com.gmaicoson.socraticmind.chat.markdown

import org.commonmark.ext.gfm.strikethrough.Strikethrough
import org.commonmark.ext.task.list.items.TaskListItemMarker
import org.commonmark.node.Code
import org.commonmark.node.Emphasis
import org.commonmark.node.HardLineBreak
import org.commonmark.node.HtmlInline
import org.commonmark.node.Image
import org.commonmark.node.Link
import org.commonmark.node.Node
import org.commonmark.node.SoftLineBreak
import org.commonmark.node.StrongEmphasis
import org.commonmark.node.Text

internal class MarkdownInlineProjection(
    private val budget: MarkdownBudget,
) {
    fun runs(parent: Node): List<MarkdownRun> {
        val result = mutableListOf<MarkdownRun>()
        parent.children().forEach { visit(it, MarkdownStyle(), null, result, 0) }
        return result
    }

    private fun visit(
        node: Node,
        style: MarkdownStyle,
        link: String?,
        result: MutableList<MarkdownRun>,
        depth: Int,
    ) {
        budget.visit(depth)
        when (node) {
            is Text -> {
                append(result, node.literal, style, link)
            }

            is HtmlInline -> {
                append(result, node.literal, style, null)
            }

            is Code -> {
                append(result, node.literal, style.copy(code = true), link)
            }

            is SoftLineBreak, is HardLineBreak -> {
                append(result, "\n", style, link)
            }

            is TaskListItemMarker -> {
                Unit
            }

            is Image -> {
                append(result, "[图片：", style, null)
                // Alt text stays readable, but an untrusted message never initiates an image request.
                val alt = mutableListOf<MarkdownRun>()
                node.children().forEach { visit(it, style, null, alt, depth + 1) }
                alt.forEach { append(result, it.text, it.style, null) }
                append(result, "]", style, null)
            }

            else -> {
                val next =
                    when (node) {
                        is StrongEmphasis -> style.copy(bold = true)
                        is Emphasis -> style.copy(italic = true)
                        is Strikethrough -> style.copy(strike = true)
                        else -> style
                    }
                val target = if (node is Link) MarkdownLink.safe(node.destination) else link
                node.children().forEach { visit(it, next, target, result, depth + 1) }
            }
        }
    }

    private fun append(
        result: MutableList<MarkdownRun>,
        text: String,
        style: MarkdownStyle,
        link: String?,
    ) {
        if (text.isEmpty()) return
        budget.literal(text)
        val last = result.lastOrNull()
        if (last?.style == style && last.link == link) {
            val merged = last.text + text
            budget.literal(merged)
            result[result.lastIndex] = last.copy(text = merged)
        } else {
            result.add(MarkdownRun(text, style, link))
        }
    }
}

internal fun Node.children(): Sequence<Node> = generateSequence(firstChild) { it.next }
