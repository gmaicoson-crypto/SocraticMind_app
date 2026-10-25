package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ChatRegenerationTest {
    @Test
    fun `active regeneration row is hidden by request ID before message IDs arrive`() {
        val source = history()
        val pending = turnRequest().pending.copy(regenerateMessageId = 102)
        val active =
            source.messages.items.last().copy(
                id = 103,
                metadata = JsonObject(mapOf("request_id" to JsonPrimitive(pending.requestId))),
            )
        val state = ChatTurnState(pending = pending)
        assertEquals(source.messages.items, (source.messages.items + active).filter(state::showsInHistory))
        val receipt = ChatTurnReceipt(pending, ChatTurnStatus.FAILED, source.messages.items.take(1))
        assertEquals(source.messages.items, (source.messages.items + active).filter(receipt::retains))
        val missingReplacement = receipt.copy(status = ChatTurnStatus.COMPLETE)
        assertEquals(
            source.messages.items.take(1),
            (source.messages.items + active).filter(missingReplacement::retains),
        )
        assertTrue(ChatTurnState().showsInHistory(active))
    }

    private fun history(account: HistoryAccount = HistoryAccount(1, 1)): ChatLibraryState =
        ChatLibraryState(
            account = account,
            selected = ChatConversation(turnRequest().pending.target),
            messages =
                HistoryPageState(
                    turnFixture().historyArray("messages").map(StoredChatMessage::decode),
                    loaded = true,
                ),
        )

    @Test
    fun `only latest compatible complete context is offered without changing question whitespace`() {
        val value = history()
        assertEquals(102L, ChatRegeneration.from(value)?.answerId)
        assertEquals(turnRequest().input, ChatRegeneration.from(value)?.input)
        assertNull(ChatRegeneration.from(value.copy(messages = value.messages.copy(loading = HistoryLoad.REFRESH))))
        val user = value.messages.items.first()
        val answer = value.messages.items.last()
        val invalid =
            listOf(
                listOf(answer),
                listOf(user),
                listOf(user.copy(id = 103), answer),
                listOf(user.copy(sessionId = "other"), answer),
                listOf(user.copy(metadata = JsonObject(mapOf("kind" to JsonPrimitive("node_overview")))), answer),
                listOf(user.copy(metadata = JsonObject(mapOf("quote" to JsonPrimitive(true)))), answer),
                listOf(user.copy(attachments = listOf(JsonObject(emptyMap()))), answer),
                listOf(user, answer.copy(metadata = JsonObject(mapOf("status" to JsonPrimitive("generating"))))),
            )
        for (items in invalid) {
            assertNull(
                ChatRegeneration.from(value.copy(messages = value.messages.copy(items = items))),
            )
        }
    }

    @Test
    fun `regeneration preserves draft persists original ID before POST and blocks double tap`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.model.edit("未发送草稿")
                val source = history(checkNotNull(h.model.state.value.account))
                h.model.regenerate(source, "标准")
                val stream = next(h.gateway.streams)
                assertEquals(102L, stream.saved?.regenerateMessageId)
                assertEquals(turnRequest().input, stream.request.input)
                assertEquals("未发送草稿", h.model.state.value.draft)
                h.model.regenerate(source, "标准")
                h.model.send("标准")
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                stream.events.send(ChatEvent.MessageIds(101, 103))
                stream.events.send(ChatEvent.Text("新回答"))
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
                assertEquals("未发送草稿", h.model.state.value.draft)
            } finally {
                h.close()
            }
        }

    @Test
    fun `stop and failed regeneration retain original while successful receipt removes only replaced answer`() =
        runBlocking {
            for (status in listOf(ChatTurnStatus.COMPLETE, ChatTurnStatus.FAILED, ChatTurnStatus.INTERRUPTED)) {
                val h = HistoryHarness(this)
                try {
                    h.login()
                    h.conversations().succeed(emptyList())
                    val source = history()
                    h.model.openConversation(checkNotNull(source.selected).target)
                    val active =
                        source.messages.items.last().copy(
                            id = 103,
                            metadata = JsonObject(mapOf("request_id" to JsonPrimitive("turn-contract-id"))),
                        )
                    h.messages().succeed(source.messages.items + active)
                    awaitHistory { h.model.state.value.messages.loaded }
                    h.model.refreshMessages()
                    val stale = h.messages()
                    val replacement = source.messages.items.map { if (it.role == "ai") it.copy(id = 103) else it }
                    val receipt =
                        ChatTurnReceipt(turnRequest().pending.copy(regenerateMessageId = 102), status, replacement)
                    h.model.accept(receipt, checkNotNull(h.model.state.value.account))
                    val expected = if (status == ChatTurnStatus.COMPLETE) listOf(103L, 101L) else listOf(102L, 101L)
                    assertEquals(
                        expected,
                        h.model.state.value.messages.items
                            .map { it.id },
                    )
                    stale.succeed(source.messages.items)
                    stale.completed.await()
                    yield()
                    assertEquals(
                        expected,
                        h.model.state.value.messages.items
                            .map { it.id },
                    )
                    h.model.accept(receipt, checkNotNull(h.model.state.value.account))
                    assertEquals(
                        expected,
                        h.model.state.value.messages.items
                            .map { it.id },
                    )
                } finally {
                    h.close()
                }
            }
        }

    @Test
    fun `restore regeneration only queries and stop remains a preservation receipt`() =
        runBlocking {
            val journal = MemoryTurnJournal()
            journal.save(turnRequest().pending.copy(regenerateMessageId = 102))
            val h = TurnHarness(this, journal)
            try {
                h.login()
                val read = next(h.gateway.statuses)
                assertEquals(102L, read.pending.regenerateMessageId)
                read.response.complete(RemoteChatTurn(ChatTurnStatus.GENERATING, ChatMessageIds(101, 103)))
                awaitHistory { h.model.state.value.canVerify }
                h.model.stop()
                next(
                    h.gateway.cancels,
                ).response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, ChatMessageIds(101, 103)))
                next(h.gateway.messages).response.complete(history().messages.items.take(1))
                awaitHistory { h.model.state.value.editable }
                assertNull(
                    h.model.state.value.receipt
                        ?.replacedMessageId,
                )
                assertTrue(
                    h.model.state.value.notice
                        .orEmpty()
                        .contains("原回答"),
                )
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                assertNull(journal.read(1))
            } finally {
                h.close()
            }
        }

    @Test
    fun `stale rejected regeneration records a stop tombstone before clearing recovery`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.model.regenerate(history(checkNotNull(h.model.state.value.account)), "标准")
                next(h.gateway.streams).events.close(HttpFailure(409, "CHAT_REGENERATE_NOT_LATEST", "stale", false))
                val stop = next(h.gateway.cancels)
                assertEquals(stop.pending, h.journal.read(1))
                stop.response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                awaitHistory { h.model.state.value.editable }
                assertNull(h.journal.read(1))
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

    @Test
    fun `old account candidate and mismatched target cannot start regeneration`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                val current = checkNotNull(h.model.state.value.account)
                h.model.regenerate(history(current.copy(revision = current.revision + 1)), "标准")
                h.model.select(ChatTarget("different"))
                h.model.regenerate(history(current), "标准")
                yield()
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                assertTrue(h.journal.records.isEmpty())
            } finally {
                h.close()
            }
        }
}
