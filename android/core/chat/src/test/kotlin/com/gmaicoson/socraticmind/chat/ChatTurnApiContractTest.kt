package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

internal fun turnFixture() =
    Json
        .parseToJsonElement(
            Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve("chat-turns.json")),
        ).historyObject()

internal fun turnRequest(): ChatTurnRequest {
    val value = turnFixture().getValue("request").historyObject()
    return ChatTurnRequest(
        PendingChatTurn(1, ChatTarget(value.historyString("session_id")), value.historyString("request_id")),
        value.historyString("user_input"),
        value.historyString("ai_style"),
    )
}

class ChatTurnApiContractTest {
    @Test
    fun `live buffer rejects identity changes terminal reversal and excessive text`() {
        val buffer = ChatTurnBuffer()
        buffer.accept(ChatEvent.MessageIds(1, 2))
        buffer.accept(ChatEvent.Text("原文"))
        assertThrows(IllegalArgumentException::class.java) { buffer.accept(ChatEvent.MessageIds(3, 4)) }
        buffer.accept(ChatEvent.RequestState("complete"))
        assertThrows(IllegalArgumentException::class.java) { buffer.accept(ChatEvent.RequestState("generating")) }
        assertThrows(IllegalArgumentException::class.java) { buffer.accept(ChatEvent.Text("迟到")) }
        assertEquals("原文", buffer.content())
        val bounded = ChatTurnBuffer()
        bounded.accept(ChatEvent.Text("x".repeat(512 * 1024)))
        assertThrows(IllegalArgumentException::class.java) { bounded.accept(ChatEvent.Text("🙂")) }
        assertEquals(512 * 1024, bounded.content().length)
        assertThrows(IllegalArgumentException::class.java) { ChatTarget(" padded ") }
    }

    @Test
    fun `wire preserves input and stable IDs then reads exact authoritative messages`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatTurnApi(transport)
                    val request = turnRequest()
                    assertEquals(turnFixture().getValue("request"), request.json())
                    val events = api.stream("turn-contract", request).toList()
                    assertEquals(ChatEvent.MessageIds(101, 102), events.first())
                    assertEquals("你好，世界🙂", events.filterIsInstance<ChatEvent.Text>().joinToString("") { it.delta })
                    assertEquals(ChatEvent.Done, events.last())
                    for (status in ChatTurnStatus.entries) {
                        assertEquals(status, api.status("turn-${status.wireValue}", request.pending).status)
                    }
                    val messages = api.messages("turn-contract", request.pending, ChatMessageIds(101, 102))
                    assertEquals(listOf(101L, 102L), messages.map { it.id })
                    assertEquals(request.input, messages.first().content)
                    assertEquals("你好，世界🙂", messages.last().content)
                    assertNull(
                        ChatHistoryApi(transport).message("turn-neighbour", request.pending.target.sessionId, 102),
                    )
                }
            }
        }

    @Test
    fun `status rejects mismatches and preserves not found deleted and unauthorized failures`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatTurnApi(transport)
                    for (item in turnFixture().historyArray("invalid_status")) {
                        val id = item.historyObject().historyString("id")
                        assertTrue(runCatching { api.status("turn-$id", turnRequest().pending) }.isFailure, id)
                    }
                    for ((token, status) in listOf("expired" to 401, "turn-missing" to 404, "turn-deleted" to 409)) {
                        val failure = runCatching { api.status(token, turnRequest().pending) }.exceptionOrNull()
                        assertTrue(failure is HttpFailure)
                        assertEquals(status, (failure as HttpFailure).status)
                    }
                }
            }
        }

    @Test
    fun `cancel supports tombstone and completion race but rejects unconfirmed responses`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    for (item in turnFixture().historyArray("cancel_cases")) {
                        val value = item.historyObject()
                        val id = value.historyString("id")
                        val result = runCatching { ChatTurnApi(transport).cancel("turn-$id", turnRequest().pending) }
                        assertEquals(
                            value
                                .getValue("valid")
                                .jsonPrimitive.content
                                .toBoolean(),
                            result.isSuccess,
                            id,
                        )
                        if (id == "tombstone") assertNull(result.getOrThrow().ids)
                        if (id == "complete") assertEquals(ChatTurnStatus.COMPLETE, result.getOrThrow().status)
                    }
                }
            }
        }

    @Test
    fun `input limit counts Unicode scalars and request IDs cannot become paths`() {
        val pending = turnRequest().pending
        assertEquals(5000, ChatTurnRequest(pending, "🙂".repeat(5000), "标准").input.codePointCount(0, 10000))
        assertThrows(IllegalArgumentException::class.java) { ChatTurnRequest(pending, "🙂".repeat(5001), "标准") }
        assertThrows(IllegalArgumentException::class.java) { ChatTurnRequest(pending, " \n\t", "标准") }
        for (id in listOf("", "../x", "x?x", "x#x", "x%2f", "x\\x", "中", "a".repeat(101))) {
            assertThrows(IllegalArgumentException::class.java) { PendingChatTurn(1, pending.target, id) }
        }
    }
}
