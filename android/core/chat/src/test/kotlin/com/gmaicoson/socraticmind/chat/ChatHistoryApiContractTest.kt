package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

class ChatHistoryApiContractTest {
    private val fixture = load("chat-history.json")
    private val sessionId = fixture.historyString("session_id")

    @Test
    fun readsBoundedPagesWithExactCursorAndOpaqueSessionQuery() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    withTimeout(10_000) {
                        val api = ChatHistoryApi(transport)
                        val sessions = api.conversations("contract-token", limit = 1)
                        assertEquals(104L, sessions.snapshotId)
                        assertEquals(sessionId, sessions.items.single().sessionId)
                        assertEquals("合成测试对话", sessions.items.single().title)
                        val olderSessions = api.conversations("contract-token", limit = 1, cursor = sessions.nextCursor)
                        assertEquals("older-session", olderSessions.items.single().sessionId)
                        assertNull(olderSessions.items.single().title)
                        assertNull(olderSessions.nextCursor)
                        val first = api.messages("contract-token", sessionId, limit = 2)
                        assertEquals(listOf(104L, 103L), first.items.map { it.id })
                        assertEquals(HistoryCursor(104, 103), first.nextCursor)
                        assertEquals(
                            StoredChatMessage.decode(fixture.historyObjectPage("messages_first")[0]),
                            first.items[0],
                        )
                        val older = api.messages("contract-token", sessionId, limit = 2, cursor = first.nextCursor)
                        assertEquals(listOf(102L, 101L), older.items.map { it.id })
                        assertNull(older.nextCursor)
                        assertEquals(104L, older.snapshotId)
                        val empty = api.messages("contract-token", "empty", limit = 2)
                        assertEquals(0L, empty.snapshotId)
                        assertNull(empty.nextCursor)
                        assertEquals(
                            emptyList<ConversationSummary>(),
                            api.conversations("contract-token", ChatMode.SOCRATIC, 1).items,
                        )
                    }
                }
            }
        }

    @Test
    fun rejectsMalformedOrMismatchedPagesFromSharedCases() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatHistoryApi(transport)
                    for (value in load("invalid-history-pages.json").historyArray("cases")) {
                        val item = value.historyObject()
                        val id = item.historyString("id")
                        val cursor =
                            item.historyOptional("cursor")?.historyObject()?.let {
                                HistoryCursor(it.historyLong("snapshot_id"), it.historyLong("before_id"))
                            }
                        var rejected = false
                        try {
                            if (item.historyString("kind") == "messages") {
                                api.messages("history-case-$id", sessionId, limit = 2, cursor = cursor)
                            } else {
                                api.conversations("history-case-$id", limit = 2, cursor = cursor)
                            }
                        } catch (_: IllegalArgumentException) {
                            rejected = true
                        } catch (_: NoSuchElementException) {
                            rejected = true
                        }
                        assertEquals(true, rejected, id)
                    }
                }
            }
        }

    @Test
    fun unauthorizedIsNotAnEmptyHistory() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatHistoryApi(transport)
                    try {
                        api.messages("expired", sessionId)
                        error("Expired credentials must fail")
                    } catch (failure: HttpFailure) {
                        assertEquals(401, failure.status)
                    }
                }
            }
        }

    @Test
    fun preservesUnknownStructuredFieldsWithoutRewritingContent() {
        val source = fixture.historyObjectPage("messages_first")[0].historyObject()
        val message = StoredChatMessage.decode(JsonObject(source + ("message_type" to JsonPrimitive("future_kind"))))
        assertEquals("future_kind", message.messageType)
        assertEquals(source.historyString("content"), message.content)
        assertEquals(source["metadata"], message.metadata)
        assertFalse(message.content.isBlank())
        assertThrows(IllegalArgumentException::class.java) { HistoryCursor(1, 2) }
        assertThrows(IllegalArgumentException::class.java) { HistoryCursor(0, 0) }
    }

    private fun load(name: String): JsonObject =
        Json
            .parseToJsonElement(
                Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve(name)),
            ).historyObject()

    private fun JsonObject.historyObjectPage(key: String) = getValue(key).historyObject().historyArray("items")
}
