package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

class ChatRegenerationContextTest {
    @Test
    fun `failed cancellation and unknown rejection keep recovery until explicit stop`() =
        runBlocking {
            for ((failure, rejected) in listOf(
                HttpFailure(400, "CHAT_QUOTE_INVALID", "unavailable", false) to true,
                HttpFailure(400, null, "legacy", false) to false,
                HttpFailure(404, "UNKNOWN", "unknown", false) to false,
                HttpFailure(500, "CHAT_QUOTE_INVALID", "server", true) to false,
                HttpFailure(422, "ATTACHMENT_NOT_READY", "not ready", true) to false,
            )) {
                val h = TurnHarness(this)
                try {
                    h.login()
                    h.ready()
                    val source = history(cases().first(), checkNotNull(h.model.state.value.account))
                    h.model.select(checkNotNull(source.selected).target)
                    h.model.edit("草稿")
                    h.model.regenerate(source, "标准")
                    val stream = next(h.gateway.streams)
                    stream.events.close(failure)
                    val unresolved = if (rejected) next(h.gateway.cancels) else next(h.gateway.statuses)
                    unresolved.response.completeExceptionally(HttpFailure(503, null, "offline", true))
                    awaitHistory { h.model.state.value.phase == ChatTurnPhase.UNRESOLVED }
                    assertEquals(stream.request.pending, h.journal.read(1))
                    assertEquals("草稿", h.model.state.value.draft)
                    assertNull(h.model.state.value.receipt)
                    assertTrue(
                        h.gateway.streams
                            .tryReceive()
                            .isFailure,
                    )
                    if (!rejected) {
                        assertTrue(
                            h.gateway.cancels
                                .tryReceive()
                                .isFailure,
                        )
                    }
                    h.model.stop()
                    next(h.gateway.cancels).response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                    awaitHistory { h.model.state.value.editable }
                    assertNull(h.journal.read(1))
                } finally {
                    h.close()
                }
            }
        }

    private fun cases() =
        Json
            .parseToJsonElement(
                Files.readString(
                    Path.of(System.getProperty("socratic.contracts")).resolve("chat-regeneration-contexts.json"),
                ),
            ).historyObject()
            .historyArray("cases")
            .map(JsonElement::historyObject)

    private fun history(
        value: JsonObject,
        account: HistoryAccount = HistoryAccount(1, 1),
    ): ChatLibraryState {
        val request = value.getValue("request").historyObject()
        val target =
            ChatTarget(
                request.historyString("session_id"),
                ChatMode.entries.single { it.wireValue == request.historyString("mode") },
                request.historyString("node_key"),
                request.historyLong("topic_id"),
            )
        return ChatLibraryState(
            account = account,
            selected = ChatConversation(target),
            messages = HistoryPageState(value.historyArray("messages").map(StoredChatMessage::decode), loaded = true),
        )
    }

    @Test
    fun `shared contexts preserve exact wire and use the existing regeneration stream`() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    for (value in cases()) {
                        val source = history(value)
                        val candidate = checkNotNull(ChatRegeneration.from(source))
                        val expected = value.getValue("request").historyObject()
                        val pending =
                            PendingChatTurn(
                                1,
                                candidate.target,
                                expected.historyString("request_id"),
                                candidate.answerId,
                            )
                        val request = ChatTurnRequest(pending, candidate.input, "标准", candidate.context)
                        assertEquals(expected, request.json(), value.historyString("name"))
                        val events = ChatTurnApi(transport).stream("turn-context", request).toList()
                        assertEquals(ChatEvent.MessageIds(101, 103), events.first())
                        assertEquals(ChatEvent.Done, events.last())
                    }
                }
            }
        }

    @Test
    fun `context bounds use scalar counts and retain immutable ordered attachment IDs`() {
        val quote = "🙂".repeat(200)
        assertEquals(quote, ChatRequestContext(quoteText = quote, quoteSourceId = Long.MAX_VALUE).quoteText)
        assertThrows(IllegalArgumentException::class.java) { ChatRequestContext(quoteText = quote + "🙂") }
        for (id in listOf(0L, -1L)) {
            assertThrows(
                IllegalArgumentException::class.java,
            ) { ChatRequestContext(quoteText = "quote", quoteSourceId = id) }
        }
        assertThrows(IllegalArgumentException::class.java) { ChatRequestContext(quoteSourceId = 1) }
        val mutable = mutableListOf("second", "first")
        val context = ChatRequestContext(attachmentIds = mutable)
        mutable.clear()
        assertEquals(listOf("second", "first"), context.attachmentIds)
        assertThrows(UnsupportedOperationException::class.java) { (context.attachmentIds as MutableList).clear() }
        assertEquals(9, ChatRequestContext(attachmentIds = (1..9).map(Int::toString)).attachmentIds.size)
        for (ids in listOf(listOf("same", "same"), listOf(""), listOf("🙂".repeat(37)), (1..10).map(Int::toString))) {
            assertThrows(IllegalArgumentException::class.java) { ChatRequestContext(attachmentIds = ids) }
        }
        assertEquals(
            "🙂".repeat(36),
            ChatRequestContext(attachmentIds = listOf("🙂".repeat(36))).attachmentIds.single(),
        )
        val pending = turnRequest().pending
        assertEquals("", ChatTurnRequest(pending, "", "标准", context).input)
        assertThrows(IllegalArgumentException::class.java) {
            ChatTurnRequest(pending, "", "标准", ChatRequestContext(quoteText = "quote"))
        }
        for (kind in listOf(ChatKind.TOPIC_OVERVIEW, ChatKind.NODE_OVERVIEW)) {
            val overview = ChatRequestContext(kind)
            assertThrows(IllegalArgumentException::class.java) { ChatTurnRequest(pending, "", "标准", overview) }
            assertThrows(
                IllegalArgumentException::class.java,
            ) { ChatRequestContext(kind, attachmentIds = listOf("id")) }
            val target = ChatTarget("topic", ChatMode.SOCRATIC, "递归", 7)
            assertEquals("", ChatTurnRequest(pending.copy(target = target), "", "标准", overview).input)
            assertThrows(IllegalArgumentException::class.java) {
                ChatTurnRequest(pending.copy(target = target.copy(topicId = 0)), "", "标准", overview)
            }
        }
    }

    @Test
    fun `malformed quote source kind and answer pairing cannot silently lose context`() {
        val source = history(cases().first())
        val question = source.messages.items.first()
        val answer = source.messages.items.last()
        val changes =
            listOf(
                "quote" to JsonPrimitive(true),
                "quote" to JsonPrimitive("x".repeat(201)),
                "quote" to JsonNull,
                "quote_source_id" to JsonPrimitive("91"),
                "quote_source_id" to JsonPrimitive(true),
                "quote_source_id" to JsonPrimitive(-1),
                "kind" to JsonPrimitive("unknown"),
                "kind" to JsonNull,
            )
        for ((key, value) in changes) {
            val changed = question.copy(metadata = JsonObject(checkNotNull(question.metadata) + (key to value)))
            assertNull(
                ChatRegeneration.from(source.copy(messages = source.messages.copy(items = listOf(changed, answer)))),
                key,
            )
        }
        for (value in listOf(JsonPrimitive(99), JsonPrimitive("101"), JsonPrimitive(true), JsonNull)) {
            val changed =
                answer.copy(
                    metadata = JsonObject(checkNotNull(answer.metadata) + ("user_message_id" to value)),
                )
            assertNull(
                ChatRegeneration.from(source.copy(messages = source.messages.copy(items = listOf(question, changed)))),
            )
        }
        // The source may be outside the loaded page; the server resolves it. Preserve Int64 without rounding.
        val exact =
            question.copy(
                metadata =
                    JsonObject(checkNotNull(question.metadata) + ("quote_source_id" to JsonPrimitive(Long.MAX_VALUE))),
            )
        assertEquals(
            Long.MAX_VALUE,
            ChatRegeneration
                .from(
                    source.copy(messages = source.messages.copy(items = listOf(exact, answer))),
                )?.context
                ?.quoteSourceId,
        )
    }

    @Test
    fun `attachment snapshot must match visible summaries including order revision and coverage`() {
        val source = history(cases().single { it.historyString("name") == "combined" })
        val question = source.messages.items.first()
        val answer = source.messages.items.last()
        val snapshots = checkNotNull(question.metadata).historyArray("attachment_snapshot")
        val first = snapshots.first().historyObject()
        val broken =
            listOf(
                question.copy(attachments = question.attachments.drop(1)),
                question.copy(attachments = question.attachments.reversed()),
                question.copy(metadata = JsonObject(checkNotNull(question.metadata) - "attachment_snapshot")),
                question.copy(
                    metadata =
                        JsonObject(checkNotNull(question.metadata) + ("attachment_snapshot" to JsonNull)),
                ),
            ) +
                listOf(
                    "revision" to JsonPrimitive(2),
                    "revision" to JsonPrimitive("1"),
                    "accepted_coverage" to JsonObject(mapOf("pages" to JsonPrimitive(1))),
                    "id" to JsonPrimitive("wrong"),
                ).map { (key, value) ->
                    question.copy(
                        metadata =
                            JsonObject(
                                checkNotNull(question.metadata) +
                                    (
                                        "attachment_snapshot" to
                                            JsonArray(listOf(JsonObject(first + (key to value)), snapshots.last()))
                                    ),
                            ),
                    )
                } +
                listOf(
                    question.copy(
                        metadata =
                            JsonObject(
                                checkNotNull(question.metadata) +
                                    ("attachment_snapshot" to JsonArray(listOf(snapshots.first(), snapshots.first()))),
                            ),
                        attachments = listOf(question.attachments.first(), question.attachments.first()),
                    ),
                )
        for (changed in broken) {
            assertNull(
                ChatRegeneration.from(source.copy(messages = source.messages.copy(items = listOf(changed, answer)))),
            )
        }
        val derived =
            answer.copy(
                metadata =
                    JsonObject(checkNotNull(answer.metadata) + ("attachment_derived" to JsonPrimitive(true))),
            )
        assertNotNull(
            ChatRegeneration.from(source.copy(messages = source.messages.copy(items = listOf(question, derived)))),
        )
    }

    @Test
    fun `all shared contexts reuse save send and receipt handoff while retaining draft`() =
        runBlocking {
            for (value in cases()) {
                val h = TurnHarness(this)
                try {
                    h.login()
                    h.ready()
                    val source = history(value, checkNotNull(h.model.state.value.account))
                    h.model.select(checkNotNull(source.selected).target)
                    h.model.edit("尚未发送的草稿")
                    h.model.regenerate(source, "标准")
                    val stream = next(h.gateway.streams)
                    val expected = value.getValue("request").historyObject()
                    assertEquals(
                        JsonObject(expected + ("request_id" to JsonPrimitive("turn-contract-id"))),
                        stream.request.json(),
                    )
                    assertEquals(stream.request.pending, stream.saved)
                    stream.events.send(ChatEvent.MessageIds(101, 103))
                    stream.events.close()
                    next(
                        h.gateway.statuses,
                    ).response.complete(RemoteChatTurn(ChatTurnStatus.COMPLETE, ChatMessageIds(101, 103)))
                    next(h.gateway.messages).response.complete(
                        source.messages.items.map {
                            if (it.role ==
                                "ai"
                            ) {
                                it.copy(id = 103)
                            } else {
                                it
                            }
                        },
                    )
                    awaitHistory { h.model.state.value.editable }
                    assertEquals(
                        102L,
                        h.model.state.value.receipt
                            ?.replacedMessageId,
                    )
                    assertEquals("尚未发送的草稿", h.model.state.value.draft)
                    assertNull(h.journal.read(1))
                } finally {
                    h.close()
                }
            }
        }

    @Test
    fun `typed unavailable context waits for confirmed cancellation and unknown errors retain recovery`() =
        runBlocking {
            val failures =
                listOf(
                    HttpFailure(400, "CHAT_QUOTE_INVALID", "gone", false),
                    HttpFailure(404, "ATTACHMENT_NOT_FOUND", "gone", false),
                    HttpFailure(422, "ATTACHMENT_SCOPE_MISMATCH", "changed", false),
                )
            for (failure in failures) {
                val h = TurnHarness(this)
                try {
                    h.login()
                    h.ready()
                    val source = history(cases().first(), checkNotNull(h.model.state.value.account))
                    h.model.select(checkNotNull(source.selected).target)
                    h.model.edit("草稿")
                    h.model.regenerate(source, "标准")
                    next(h.gateway.streams).events.close(failure)
                    val stop = next(h.gateway.cancels)
                    assertEquals(stop.pending, h.journal.read(1))
                    assertFalse(h.model.state.value.editable)
                    stop.response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                    awaitHistory { h.model.state.value.editable }
                    assertNull(h.journal.read(1))
                    assertEquals("草稿", h.model.state.value.draft)
                    assertNull(
                        h.model.state.value.receipt
                            ?.replacedMessageId,
                    )
                    assertTrue(
                        h.gateway.statuses
                            .tryReceive()
                            .isFailure,
                    )
                } finally {
                    h.close()
                }
            }
            for (failure in listOf(
                HttpFailure(400, null, "legacy", false),
                HttpFailure(404, "UNKNOWN", "unknown", false),
                HttpFailure(500, "CHAT_QUOTE_INVALID", "server", true),
            )) {
                assertFalse(ChatRegeneration.rejected(failure))
            }
        }
}
