package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

internal fun feedbackFixture(name: String = "chat-feedback.json") =
    Json
        .parseToJsonElement(
            Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve(name)),
        ).historyObject()

internal fun feedbackValue(
    code: String,
    status: ChatTurnStatus = ChatTurnStatus.FAILED,
) = ChatAnswerFeedback.decode(
    JsonObject(mapOf("error_code" to JsonPrimitive(code), "usage" to feedbackFixture().getValue("reported_usage"))),
    status,
)

class ChatFeedbackContractTest {
    @Test
    fun `raw decimal and unrepresentable usage never block terminal status history or cancel`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatTurnApi(transport)
                    for (item in feedbackFixture("chat-feedback-wire.json").historyArray("cases")) {
                        val case = item.historyObject()
                        if (!case.getValue("valid_state").jsonPrimitive.boolean) continue
                        val token = "turn-feedback-wire-${case.historyString("name")}"
                        val expected =
                            case
                                .historyOptional("expected_total")
                                ?.jsonPrimitive
                                ?.content
                                ?.toLong()
                        val state = api.status(token, turnRequest().pending)
                        assertEquals(ChatTurnStatus.INTERRUPTED, state.status)
                        assertEquals("AI_TIMEOUT", state.feedback?.failure?.code)
                        assertEquals(expected, state.feedback?.usage?.total)
                        val cancelled = api.cancel(token, turnRequest().pending)
                        assertEquals(state.status, cancelled.status)
                        assertEquals(expected, cancelled.feedback?.usage?.total)
                        val answer = api.messages(token, turnRequest().pending, checkNotNull(state.ids)).last()
                        val feedback = checkNotNull(ChatAnswerFeedback.from(answer))
                        assertEquals(expected, feedback.usage?.total)
                        assertEquals("AI_TIMEOUT", feedback.failure?.code)
                    }
                }
            }
        }

    @Test
    fun `invalid optional feedback cannot weaken core identity status or message ids`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    for (item in feedbackFixture("chat-feedback-wire.json").historyArray("cases")) {
                        val case = item.historyObject()
                        if (case.getValue("valid_state").jsonPrimitive.boolean) continue
                        val token = "turn-feedback-wire-${case.historyString("name")}"
                        val result = runCatching { ChatTurnApi(transport).status(token, turnRequest().pending) }
                        assertTrue(result.isFailure)
                    }
                }
            }
        }

    @Test
    fun `shared usage cases stay exact or unknown across status history and cancellation`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatTurnApi(transport)
                    for (item in feedbackFixture().historyArray("usage_cases")) {
                        val case = item.historyObject()
                        val token = "turn-feedback-usage-${case.historyString("name")}"
                        val state = api.status(token, turnRequest().pending)
                        val expected = ReportedTokenUsage.decode(case["expected"])
                        assertEquals(expected, state.feedback?.usage, case.historyString("name"))
                        assertEquals(expected, api.cancel(token, turnRequest().pending).feedback?.usage)
                        val answer = api.messages(token, turnRequest().pending, checkNotNull(state.ids)).last()
                        assertEquals(expected, ChatAnswerFeedback.from(answer)?.usage)
                        assertNull(state.feedback?.failure)
                        assertEquals(case["expected"] == JsonNull, state.feedback?.usageSummary?.contains("未知"))
                    }
                }
            }
        }

    @Test
    fun `shared errors use local safe descriptions and retain the answer report`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatTurnApi(transport)
                    for (item in feedbackFixture().historyArray("errors")) {
                        val case = item.historyObject()
                        val token = "turn-feedback-error-${case.historyString("kind")}"
                        val state = api.status(token, turnRequest().pending)
                        val feedback = checkNotNull(state.feedback)
                        assertEquals(case.historyString("code"), feedback.failure?.code)
                        assertEquals(case.historyString("message"), feedback.failure?.message)
                        assertEquals(case.getValue("retryable").jsonPrimitive.boolean, feedback.failure?.retryable)
                        assertEquals(59L, feedback.usage?.total)
                        val answer = api.messages(token, turnRequest().pending, checkNotNull(state.ids)).last()
                        assertEquals(feedback, ChatAnswerFeedback.from(answer))
                        assertFalse(feedback.toString().contains("synthetic-private-key"))
                    }
                }
            }
        }

    @Test
    fun `legacy responses remain valid and unknown errors never echo provider text`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val state = ChatTurnApi(transport).status("turn-contract", turnRequest().pending)
                    assertNull(state.feedback?.usage)
                    assertNull(state.feedback?.failure)
                }
            }
            val unknown = feedbackValue("private-key-".repeat(10000))
            assertEquals("AI_STREAM_ERROR", unknown.failure?.code)
            assertFalse(unknown.toString().contains("private-key"))
            assertTrue(unknown.toString().length < 300)
            assertNull(feedbackValue("AI_QUOTA_EXCEEDED", ChatTurnStatus.COMPLETE).failure)
            assertNull(feedbackValue("AI_TIMEOUT", ChatTurnStatus.GENERATING).failure)
        }

    @Test
    fun `history only presents stable AI answers and does not mistake missing for zero`() {
        val messages = turnFixture().historyArray("messages").map(StoredChatMessage::decode)
        assertNull(ChatAnswerFeedback.from(messages.first()))
        for (status in listOf("streaming", "generating", "superseded")) {
            assertNull(
                ChatAnswerFeedback.from(
                    messages.last().copy(
                        metadata =
                            JsonObject(
                                mapOf("status" to JsonPrimitive(status)),
                            ),
                    ),
                ),
            )
        }
        for (status in listOf("failed", "interrupted")) {
            val metadata = JsonObject(mapOf("status" to JsonPrimitive(status)))
            assertEquals(
                "AI_STREAM_ERROR",
                ChatAnswerFeedback.from(messages.last().copy(metadata = metadata))?.failure?.code,
            )
        }
        val zero = ChatAnswerFeedback(ReportedTokenUsage.decode(feedbackFixture()["zero_usage"]), null)
        assertTrue(zero.usageSummary.contains("合计 0"))
        assertFalse(zero.usageSummary.contains("未知"))
        assertTrue(checkNotNull(ChatAnswerFeedback.from(messages.last())).usageSummary.contains("未知"))
    }
}
