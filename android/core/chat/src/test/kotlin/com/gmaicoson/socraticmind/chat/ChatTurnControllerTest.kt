package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.network.ChatEvent
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.IOException

class ChatTurnControllerTest {
    @Test
    fun `failure after journal deletion still hands confirmed messages to history`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.begin().events.close()
                h.journal.failAfterClear = true
                h.resolve(next(h.gateway.statuses))
                assertEquals(ChatTurnPhase.STORAGE_FAILED, h.model.state.value.phase)
                assertNull(h.journal.records[1])
                val receipt = checkNotNull(h.model.state.value.receipt)
                assertEquals("你好，世界🙂", receipt.messages.last().content)
                h.model.verify()
                awaitHistory { h.model.state.value.editable }
                assertEquals(receipt, h.model.state.value.receipt)
                assertTrue(
                    h.gateway.statuses
                        .tryReceive()
                        .isFailure,
                )
                h.model.acknowledge(receipt)
                assertNull(h.model.state.value.receipt)
            } finally {
                h.close()
            }
        }

    @Test
    fun `completion remains available across selection changes until history acknowledges`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.begin().events.close()
                h.resolve(next(h.gateway.statuses))
                h.model.select(ChatTarget("next-session"))
                h.model.edit("next question")
                h.model.send("标准")
                assertNotNull(h.model.state.value.receipt)
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                val receipt = checkNotNull(h.model.state.value.receipt)
                h.model.acknowledge(receipt.copy(pending = receipt.pending.copy(requestId = "different")))
                assertTrue(!h.model.state.value.canSend)
                h.model.acknowledge(receipt)
                assertNull(h.model.state.value.receipt)
                assertTrue(h.model.state.value.canSend)
            } finally {
                h.close()
            }
        }

    @Test
    fun `persist before POST suppress double send and DONE requires authoritative status`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                val stream = h.begin()
                assertEquals(stream.request.pending, stream.saved)
                h.model.send("标准")
                h.model.edit("must not replace submitted input")
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                stream.events.send(ChatEvent.MessageIds(101, 102))
                stream.events.send(ChatEvent.Text("provisional"))
                stream.events.send(ChatEvent.Done)
                stream.events.close()
                val status = next(h.gateway.statuses)
                assertEquals(ChatTurnPhase.VERIFYING, h.model.state.value.phase)
                assertNull(h.model.state.value.receipt)
                assertNotNull(h.journal.records[1])
                h.resolve(status)
                assertEquals(
                    "你好，世界🙂",
                    h.model.state.value.receipt
                        ?.messages
                        ?.last()
                        ?.content,
                )
                assertTrue(
                    h.model.state.value.partial
                        .isEmpty(),
                )
                assertNull(h.journal.records[1])
            } finally {
                h.close()
            }
        }

    @Test
    fun `disconnect and 404 stay unresolved and retry is GET only`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                val stream = h.begin()
                stream.events.send(ChatEvent.Text("partial"))
                stream.events.close(IOException("lost connection"))
                next(
                    h.gateway.statuses,
                ).response.completeExceptionally(HttpFailure(404, "CHAT_REQUEST_NOT_FOUND", "missing", null))
                awaitHistory { h.model.state.value.phase == ChatTurnPhase.UNRESOLVED }
                assertEquals("partial", h.model.state.value.partial)
                h.model.send("标准")
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                h.model.verify()
                h.resolve(next(h.gateway.statuses))
                assertNull(h.journal.records[1])
            } finally {
                h.close()
            }
        }

    @Test
    fun `cancel racing completion displays the completed response`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.begin()
                h.model.stop()
                assertEquals(ChatTurnPhase.STOPPING, h.model.state.value.phase)
                h.resolve(next(h.gateway.cancels))
                assertEquals(
                    ChatTurnStatus.COMPLETE,
                    h.model.state.value.receipt
                        ?.status,
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
    fun `failed cancel can retry durable tombstone without inventing messages`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.begin()
                h.model.stop()
                next(h.gateway.cancels).response.completeExceptionally(IOException("offline"))
                awaitHistory { h.model.state.value.phase == ChatTurnPhase.UNRESOLVED }
                assertNotNull(h.journal.records[1])
                h.model.stop()
                next(h.gateway.cancels).response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                awaitHistory { h.model.state.value.editable }
                assertEquals(
                    ChatTurnStatus.INTERRUPTED,
                    h.model.state.value.receipt
                        ?.status,
                )
                assertTrue(
                    h.model.state.value.receipt!!
                        .messages
                        .isEmpty(),
                )
                assertTrue(
                    h.gateway.messages
                        .tryReceive()
                        .isFailure,
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `new controller restores only IDs and bounded polling never reposts`() =
        runBlocking {
            val journal = MemoryTurnJournal()
            journal.save(turnRequest().pending)
            val h = TurnHarness(this, journal)
            try {
                h.login()
                next(
                    h.gateway.statuses,
                ).response.complete(RemoteChatTurn(ChatTurnStatus.GENERATING, ChatMessageIds(101, 102)))
                awaitHistory { h.model.state.value.phase == ChatTurnPhase.UNRESOLVED }
                assertEquals(turnRequest().pending.target, h.model.state.value.target)
                assertEquals("", h.model.state.value.submitted)
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                h.model.verify()
                h.resolve(next(h.gateway.statuses))
                assertNull(journal.records[1])
            } finally {
                h.close()
            }
        }

    @Test
    fun `save failure before or after persistence never sends and retains the draft`() =
        runBlocking {
            for (after in listOf(false, true)) {
                val h = TurnHarness(this)
                try {
                    h.login()
                    h.ready()
                    h.journal.failSave = !after
                    h.journal.failAfterSave = after
                    h.model.send("标准")
                    awaitHistory { h.model.state.value.phase == ChatTurnPhase.STORAGE_FAILED }
                    assertEquals(turnRequest().input, h.model.state.value.draft)
                    assertTrue(
                        h.gateway.streams
                            .tryReceive()
                            .isFailure,
                    )
                    h.journal.failSave = false
                    h.journal.failAfterSave = false
                    h.model.verify()
                    if (after) {
                        next(h.gateway.statuses).response.completeExceptionally(HttpFailure(404, null, "unknown", null))
                        awaitHistory { h.model.state.value.phase == ChatTurnPhase.UNRESOLVED }
                    } else {
                        awaitHistory { h.model.state.value.editable }
                    }
                } finally {
                    h.close()
                }
            }
        }

    @Test
    fun `journal read and clear failures block new sends until recovery succeeds`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.journal.failRead = true
                h.login()
                awaitHistory { h.model.state.value.phase == ChatTurnPhase.STORAGE_FAILED }
                h.journal.failRead = false
                h.model.verify()
                h.ready()
                h.begin().events.close()
                h.journal.failClear = true
                h.resolve(next(h.gateway.statuses))
                assertEquals(ChatTurnPhase.STORAGE_FAILED, h.model.state.value.phase)
                assertNotNull(h.journal.records[1])
                h.journal.failClear = false
                h.model.verify()
                h.resolve(next(h.gateway.statuses))
                assertNull(h.journal.records[1])
            } finally {
                h.close()
            }
        }

    @Test
    fun `old noncooperative status and 401 cannot leak into a new account`() =
        runBlocking {
            for (unauthorized in listOf(false, true)) {
                val h = TurnHarness(this)
                try {
                    h.login()
                    h.ready()
                    h.begin().events.close()
                    val old = next(h.gateway.statuses)
                    h.model.clear()
                    h.session.logout()
                    h.login(2)
                    awaitHistory { h.model.state.value.editable }
                    if (unauthorized) {
                        old.response.completeExceptionally(HttpFailure(401, null, "expired", null))
                    } else {
                        old.response.complete(RemoteChatTurn(ChatTurnStatus.COMPLETE, ChatMessageIds(101, 102)))
                    }
                    old.completed.await()
                    yield()
                    assertEquals(2L, (h.session.state.value as SessionState.SignedIn).user.id)
                    assertEquals(
                        2L,
                        h.model.state.value.account
                            ?.userId,
                    )
                    assertNull(h.model.state.value.receipt)
                    assertTrue(
                        h.gateway.messages
                            .tryReceive()
                            .isFailure,
                    )
                    assertNotNull(h.journal.records[1])
                } finally {
                    h.close()
                }
            }
        }

    @Test
    fun `current 401 clears state and deleted request becomes terminal without a new POST`() =
        runBlocking {
            for (deleted in listOf(false, true)) {
                val h = TurnHarness(this)
                try {
                    h.login()
                    h.ready()
                    h.begin().events.close()
                    next(h.gateway.statuses).response.completeExceptionally(
                        HttpFailure(
                            if (deleted) 409 else 401,
                            if (deleted) "CHAT_REQUEST_DELETED" else null,
                            "changed",
                            null,
                        ),
                    )
                    if (deleted) {
                        awaitHistory { h.model.state.value.editable }
                        assertTrue(
                            h.model.state.value.receipt!!
                                .messages
                                .isEmpty(),
                        )
                        assertNull(h.journal.records[1])
                    } else {
                        awaitHistory { h.model.state.value.account == null }
                        assertEquals(SessionState.SignedOut(expired = true), h.session.state.value)
                        assertNotNull(h.journal.records[1])
                    }
                } finally {
                    h.close()
                }
            }
        }

    @Test
    fun `late verification cannot override a confirmed stop`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.begin().events.close()
                val old = next(h.gateway.statuses)
                h.model.stop()
                next(h.gateway.cancels).response.complete(RemoteChatTurn(ChatTurnStatus.INTERRUPTED, null))
                awaitHistory { h.model.state.value.editable }
                old.response.complete(RemoteChatTurn(ChatTurnStatus.COMPLETE, ChatMessageIds(101, 102)))
                old.completed.await()
                yield()
                assertEquals(
                    ChatTurnStatus.INTERRUPTED,
                    h.model.state.value.receipt
                        ?.status,
                )
                assertTrue(
                    h.gateway.messages
                        .tryReceive()
                        .isFailure,
                )
            } finally {
                h.close()
            }
        }
}
