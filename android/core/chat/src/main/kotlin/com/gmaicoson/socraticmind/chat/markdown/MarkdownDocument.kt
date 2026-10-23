package com.gmaicoson.socraticmind.chat.markdown

data class MarkdownStyle(
    val bold: Boolean = false,
    val italic: Boolean = false,
    val strike: Boolean = false,
    val code: Boolean = false,
)

/** Links are already validated. HTML and images are never executable view content. */
data class MarkdownRun(
    val text: String,
    val style: MarkdownStyle = MarkdownStyle(),
    val link: String? = null,
)

enum class MarkdownAlignment { LEFT, CENTER, RIGHT }

data class MarkdownTable(
    val alignments: List<MarkdownAlignment>,
    val rows: List<List<List<MarkdownRun>>>,
)

sealed interface MarkdownContent {
    data class Text(
        val runs: List<MarkdownRun>,
        val heading: Int = 0,
    ) : MarkdownContent

    data class Code(
        val text: String,
        val language: String,
    ) : MarkdownContent

    data class Table(
        val value: MarkdownTable,
    ) : MarkdownContent

    data object Rule : MarkdownContent
}

/** Containers are flattened for lazy UI consumption; list markers belong only to the first child block. */
data class MarkdownBlock(
    val content: MarkdownContent,
    val quoteDepth: Int = 0,
    val indent: Int = 0,
    val marker: String? = null,
)

data class MarkdownDocument(
    val blocks: List<MarkdownBlock>,
    val plainFallback: Boolean = false,
)

internal class MarkdownLimit : RuntimeException()

internal class MarkdownBudget {
    private var nodes = 0

    fun visit(depth: Int) {
        if (++nodes > 4096 || depth > 32) throw MarkdownLimit()
    }

    fun literal(value: String) {
        if (value.toByteArray(Charsets.UTF_8).size > 16 * 1024) throw MarkdownLimit()
    }

    companion object {
        // Conservative preflight bounds recursive library conversion before our AST budget can run.
        fun accepts(source: String): Boolean {
            val bytes = source.toByteArray(Charsets.UTF_8)
            if (bytes.size > 128 * 1024) return false
            var markers = 0
            var lines = 1
            var pipes = 0
            for (byte in bytes) {
                when (byte.toInt()) {
                    42, 45, 62, 91, 93, 95, 126 -> {
                        markers++
                    }

                    10 -> {
                        lines++
                        pipes = 0
                    }

                    124 -> {
                        pipes++
                    }
                }
                if (markers > 256 || lines > 1024 || pipes > 64) return false
            }
            return true
        }
    }
}

/** Keep every Unicode scalar and original newline, including when rich parsing exceeds its budget. */
internal fun plainMarkdown(source: String): MarkdownDocument {
    val blocks = mutableListOf<MarkdownBlock>()
    var start = 0
    while (start < source.length) {
        var end = minOf(start + 2048, source.length)
        if (end < source.length && source[end - 1].isHighSurrogate() && source[end].isLowSurrogate()) end--
        blocks.add(MarkdownBlock(MarkdownContent.Text(listOf(MarkdownRun(source.substring(start, end))))))
        start = end
    }
    return MarkdownDocument(blocks, plainFallback = true)
}
