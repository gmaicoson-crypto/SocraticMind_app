package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.IOException

class ChatModelSendTest {
    private val rejected = HttpFailure(422, "LLM_MODEL_UNAVAILABLE", "synthetic rejection", false)

    @Test
    fun `typed rejection waits for durable stop and preserves input after a failed cancellation retry`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.model.setModelSelection(checkNotNull(h.model.state.value.account), "env:first", true)
                val stream = h.begin()
                stream.events.close(rejected)
                val first = next(h.gateway.cancels)
                assertEquals(stream.request.pending, h.journal.read(1))
                assertEquals("", h.model.state.value.draft)
                first.response.completeExceptionally(IOException("offline"))
                awaitHistory { h.model.state.value.phase == ChatTurnPhase.UNRESOLVED }
                assertEquals(stream.request.input, h.model.state.value.submitted)
                h.model.stop()
                next(h.gateway.cancels).response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                awaitHistory { h.model.state.value.editable }
                assertEquals(stream.request.input, h.model.state.value.draft)
                assertTrue(
                    h.model.state.value.notice
                        ?.contains("模型不可用") == true,
                )
                assertNull(h.journal.read(1))
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
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
    fun `confirmed model rejection preserves draft even if journal clearing fails before or after deletion`() =
        runBlocking {
            for (after in listOf(false, true)) {
                val h = TurnHarness(this)
                try {
                    h.login()
                    h.ready()
                    val stream = h.begin()
                    stream.events.close(rejected)
                    h.journal.failClear = !after
                    h.journal.failAfterClear = after
                    next(h.gateway.cancels).response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                    awaitHistory { h.model.state.value.phase == ChatTurnPhase.STORAGE_FAILED }
                    assertEquals(stream.request.input, h.model.state.value.draft)
                    assertFalse(h.model.state.value.canSend)
                    h.journal.failClear = false
                    h.journal.failAfterClear = false
                    h.model.verify()
                    if (!after) {
                        next(
                            h.gateway.statuses,
                        ).response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                    }
                    awaitHistory { h.model.state.value.editable }
                    assertEquals(stream.request.input, h.model.state.value.draft)
                    assertNull(h.journal.read(1))
                    assertTrue(
                        h.gateway.streams
                            .tryReceive()
                            .isFailure,
                    )
                } finally {
                    h.close()
                }
            }
        }

    @Test
    fun `generic validation or wrong-status model errors still query and never assume a preflight rejection`() =
        runBlocking {
            for (error in listOf(
                HttpFailure(422, "VALIDATION_ERROR", "invalid", false),
                HttpFailure(500, "LLM_MODEL_UNAVAILABLE", "server failure", false),
            )) {
                val h = TurnHarness(this)
                try {
                    h.login()
                    h.ready()
                    h.begin().events.close(error)
                    val status = next(h.gateway.statuses)
                    assertTrue(
                        h.gateway.cancels
                            .tryReceive()
                            .isFailure,
                    )
                    status.response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                    awaitHistory { h.model.state.value.editable }
                    assertEquals("", h.model.state.value.draft)
                } finally {
                    h.close()
                }
            }
        }

    @Test
    fun `regeneration uses current choice and rejection retains old answer and separate draft`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.model.edit("保留草稿🙂")
                val account = checkNotNull(h.model.state.value.account)
                val source =
                    ChatLibraryState(
                        account = account,
                        selected = ChatConversation(turnRequest().pending.target),
                        messages =
                            HistoryPageState(
                                turnFixture().historyArray("messages").map(StoredChatMessage::decode),
                                loaded = true,
                            ),
                    )
                h.model.setModelSelection(account, "env:second", true)
                h.model.regenerate(source, "标准")
                val stream = next(h.gateway.streams)
                assertEquals("env:second", stream.request.model)
                assertEquals(turnRequest().input, stream.request.input)
                assertEquals(102L, stream.request.pending.regenerateMessageId)
                stream.events.close(rejected)
                next(h.gateway.cancels).response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                awaitHistory { h.model.state.value.editable }
                assertEquals("保留草稿🙂", h.model.state.value.draft)
                val receipt = checkNotNull(h.model.state.value.receipt)
                assertNull(receipt.replacedMessageId)
                assertEquals(source.messages.items, source.messages.items.filter(receipt::retains))
            } finally {
                h.close()
            }
        }

    @Test
    fun `changing selection discards stale suggestion confirmation and sends the confirmed current model`() =
        runBlocking {
            val h = SuggestionsHarness(this)
            try {
                h.login()
                h.model.setModel("é")
                h.model.setActive(true)
                val old = h.gateway.next()
                assertEquals("é", old.model)
                old.succeed("旧建议")
                awaitHistory { !h.model.state.value.loading }
                h.base.turn.edit("手写草稿")
                h.model.choose("旧建议", checkNotNull(h.model.state.value.context), "标准")
                assertTrue(h.model.state.value.choice != null)
                h.model.setModel("e\u0301")
                h.model.confirmChoice("标准")
                assertNull(h.model.state.value.choice)
                assertTrue(
                    h.base.turnGateway.streams
                        .tryReceive()
                        .isFailure,
                )
                val current = h.gateway.next()
                assertEquals("e\u0301", current.model)
                current.succeed("新建议")
                awaitHistory { !h.model.state.value.loading }
                h.model.choose("新建议", checkNotNull(h.model.state.value.context), "标准")
                h.model.confirmChoice("标准")
                val stream = next(h.base.turnGateway.streams)
                assertEquals("e\u0301", stream.request.model)
                assertEquals("新建议", stream.request.input)
            } finally {
                h.close()
            }
        }

    @Test
    fun `unavailable choice disables suggestion actions and ignores a late generated suggestion`() =
        runBlocking {
            val h = SuggestionsHarness(this)
            try {
                h.login()
                h.model.setModel("env:first")
                h.model.setActive(true)
                val read = h.gateway.next()
                val context = checkNotNull(h.model.state.value.context)
                h.base.turn.setModelSelection(context.account, "env:first", false)
                h.model.refresh()
                read.succeed("迟到建议")
                read.completed.await()
                yield()
                assertFalse(h.model.state.value.enabled)
                h.model.choose("迟到建议", context, "标准")
                assertTrue(
                    h.base.turnGateway.streams
                        .tryReceive()
                        .isFailure,
                )
                assertEquals(1, h.gateway.count)
            } finally {
                h.close()
            }
        }
}
