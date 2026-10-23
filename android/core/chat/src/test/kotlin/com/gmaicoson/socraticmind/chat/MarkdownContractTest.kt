package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.chat.markdown.MarkdownBlock
import com.gmaicoson.socraticmind.chat.markdown.MarkdownContent
import com.gmaicoson.socraticmind.chat.markdown.MarkdownLink
import com.gmaicoson.socraticmind.chat.markdown.MarkdownParser
import com.gmaicoson.socraticmind.chat.markdown.MarkdownRun
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

class MarkdownContractTest {
    private val fixture =
        Json
            .parseToJsonElement(
                Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve("message-markdown.json")),
            ).jsonObject

    @Test
    fun projectsSharedFormattingAndLiteralSafetyCases() {
        for (value in fixture.getValue("cases").jsonArray) {
            val item = value.jsonObject
            val id = item.getValue("id").jsonPrimitive.content
            val result = MarkdownParser.parse(item.getValue("source").jsonPrimitive.content)
            assertFalse(result.plainFallback, id)
            assertEquals(item.getValue("blocks"), JsonArray(result.blocks.map(::snapshot)), id)
        }
    }

    @Test
    fun appliesTheSameWebLinkPolicyOnBothPlatforms() {
        for (value in fixture.getValue("links").jsonArray) {
            val item = value.jsonObject
            val input = item.getValue("input").jsonPrimitive.content
            assertEquals(item.getValue("safe").jsonPrimitive.contentOrNull, MarkdownLink.safe(input), input)
        }
    }

    @Test
    fun boundedFallbackPreservesEveryScalarAndNewline() {
        val wideRow = "|" + List(33) { "a" }.joinToString("|") + "|\n"
        val wideDivider = "|" + List(33) { "---" }.joinToString("|") + "|\n"
        val cases =
            listOf(
                "中文🙂é\n".repeat(20_000),
                "```\n" + "x".repeat(16 * 1024 + 1) + "\n```",
                "*".repeat(300) + "保留",
                "> ".repeat(40) + "深层",
                "段落\n\n".repeat(513),
                wideRow + wideDivider + wideRow,
                "|a|b|c|\n|---|---|---|\n" + "|x|y|z|\n".repeat(684),
            )
        for ((index, source) in cases.withIndex()) {
            val result = MarkdownParser.parse(source)
            assertTrue(result.plainFallback, "case $index")
            val chunks = result.blocks.map { (it.content as MarkdownContent.Text).runs.single().text }
            assertEquals(source, chunks.joinToString(""), "case $index")
            assertTrue(chunks.all { it.length <= 2048 && !it.first().isLowSurrogate() && !it.last().isHighSurrogate() })
        }
    }

    private fun snapshot(block: MarkdownBlock): JsonObject =
        buildJsonObject {
            if (block.quoteDepth != 0) put("quote", block.quoteDepth)
            if (block.indent != 0) put("indent", block.indent)
            block.marker?.let { put("marker", it) }
            when (val content = block.content) {
                is MarkdownContent.Text -> {
                    put("type", "text")
                    put("runs", runs(content.runs))
                    if (content.heading != 0) put("heading", content.heading)
                }

                is MarkdownContent.Code -> {
                    put("type", "code")
                    put("text", content.text)
                    put("language", content.language)
                }

                is MarkdownContent.Table -> {
                    put("type", "table")
                    put("alignments", JsonArray(content.value.alignments.map { JsonPrimitive(it.name.lowercase()) }))
                    put("rows", JsonArray(content.value.rows.map { row -> JsonArray(row.map(::runs)) }))
                }

                MarkdownContent.Rule -> {
                    put("type", "rule")
                }
            }
        }

    private fun runs(values: List<MarkdownRun>) =
        JsonArray(
            values.map { run ->
                buildJsonObject {
                    put("text", run.text)
                    if (run.style.bold) put("bold", true)
                    if (run.style.italic) put("italic", true)
                    if (run.style.strike) put("strike", true)
                    if (run.style.code) put("code", true)
                    run.link?.let { put("link", it) }
                }
            },
        )
}
