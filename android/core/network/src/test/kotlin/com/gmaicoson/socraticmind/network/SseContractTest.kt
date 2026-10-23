package com.gmaicoson.socraticmind.network

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestFactory
import java.nio.file.Files
import java.nio.file.Path

class SseContractTest {
    @TestFactory
    fun framingAtEveryBoundary(): List<DynamicTest> =
        cases("sse-framing.json").map { case ->
            DynamicTest.dynamicTest(case.string("id")) {
                val expected = case.getValue("payloads").jsonArray.map { it.jsonPrimitive.content }
                for (chunks in allPartitions(case.string("wire"))) {
                    val decoder = SseDecoder()
                    val actual = chunks.flatMap(decoder::feed)
                    decoder.finish()
                    assertEquals(expected, actual)
                }
            }
        }

    @TestFactory
    fun providerFramesAtEveryBoundary(): List<DynamicTest> =
        cases("chat-streams.json").map { case ->
            DynamicTest.dynamicTest(case.string("id")) {
                for (chunks in allPartitions(case.string("wire"))) {
                    val decoder = SseDecoder()
                    val events = chunks.flatMap(decoder::feed).flatMap(ChatEventDecoder::decode)
                    decoder.finish()
                    assertEquals(
                        case.string("text"),
                        events.filterIsInstance<ChatEvent.Text>().joinToString("") { it.delta },
                    )
                    assertEquals(listOf(ChatEvent.MessageIds(1, 2)), events.filterIsInstance<ChatEvent.MessageIds>())
                    assertEquals(
                        listOf(case.string("status")),
                        events.filterIsInstance<ChatEvent.RequestState>().map { it.status },
                    )
                    assertEquals(ChatEvent.Done, events.last())
                    val failures = events.filterIsInstance<ChatEvent.Failure>()
                    if (case.string("status") == "interrupted") {
                        assertEquals(listOf(ChatEvent.Failure("AI_STREAM_INCOMPLETE", "测试流中断", true)), failures)
                    } else {
                        assertTrue(failures.isEmpty())
                    }
                }
            }
        }

    @TestFactory
    fun rejectMalformedChatEvents(): List<DynamicTest> =
        fixture("invalid-chat-events.json")
            .getValue("payloads")
            .jsonArray
            .map { payload ->
                DynamicTest.dynamicTest(payload.jsonPrimitive.content) {
                    assertThrows(Exception::class.java) { ChatEventDecoder.decode(payload.jsonPrimitive.content) }
                }
            }

    @Test
    fun malformedUtf8ClosesParser() {
        val decoder = SseDecoder()
        assertThrows(Exception::class.java) { decoder.feed(byteArrayOf(0xc3.toByte(), 10)) }
        assertThrows(IllegalStateException::class.java) { decoder.feed(byteArrayOf()) }
    }

    @Test
    fun lineAndEventLimitsAreIndependent() {
        val atLimit = SseDecoder(maxLineBytes = 7, maxEventBytes = 7)
        assertEquals(listOf("a"), atLimit.feed("data: a\n\n".toByteArray()))
        val longLine = SseDecoder(maxLineBytes = 7)
        assertThrows(IllegalArgumentException::class.java) { longLine.feed("data: ab".toByteArray()) }
        val longEvent = SseDecoder(maxLineBytes = 7, maxEventBytes = 13)
        assertThrows(IllegalArgumentException::class.java) { longEvent.feed("data: a\ndata: b\n".toByteArray()) }
        assertThrows(IllegalStateException::class.java) { longEvent.feed(byteArrayOf()) }
    }

    @Test
    fun doneAndUnknownStateDoNotInventSuccess() {
        assertEquals(listOf(ChatEvent.Done), ChatEventDecoder.decode("[DONE]"))
        assertEquals(
            listOf(ChatEvent.RequestState("future-state")),
            ChatEventDecoder.decode("""{"request_state":{"status":"future-state"}}"""),
        )
        assertTrue(ChatEventDecoder.decode("""{"type":"future-event","extra":1}""").single() is ChatEvent.Extension)
    }

    @Test
    fun endOfFileDiscardsIncompleteEventAndClosesParser() {
        val decoder = SseDecoder()
        assertEquals(emptyList<String>(), decoder.feed("data: pending\n".toByteArray()))
        decoder.finish()
        assertThrows(IllegalStateException::class.java) { decoder.feed("\n".toByteArray()) }
    }

    private fun fixture(name: String): JsonObject {
        val root = Path.of(System.getProperty("socratic.contracts"))
        return Json.parseToJsonElement(Files.readString(root.resolve(name))).jsonObject
    }

    private fun cases(name: String): List<JsonObject> = fixture(name).getValue("cases").jsonArray.map { it.jsonObject }

    private fun JsonObject.string(name: String): String = getValue(name).jsonPrimitive.content

    private fun allPartitions(wire: String): Sequence<List<ByteArray>> =
        sequence {
            val bytes = wire.toByteArray(Charsets.UTF_8)
            for (cut in 0..bytes.size) yield(listOf(bytes.copyOfRange(0, cut), bytes.copyOfRange(cut, bytes.size)))
            yield(bytes.map { byteArrayOf(it) })
        }
}
