package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.IOException

class ChatLibraryControllerTest {
    @Test
    fun `confirmed turn merges stable IDs and invalidates a stale history refresh`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                val pending = turnRequest().pending
                h.login()
                h.conversations().succeed(listOf(summary(100, pending.target.sessionId)))
                awaitHistory { h.model.state.value.conversations.loaded }
                h.model.selectConversation(pending.target.sessionId)
                h.messages().succeed(listOf(message(100, pending.target.sessionId)))
                awaitHistory { h.model.state.value.messages.loaded }
                h.model.refreshMessages()
                val stale = h.messages()
                val account = checkNotNull(h.model.state.value.account)
                val receipt =
                    ChatTurnReceipt(
                        pending,
                        ChatTurnStatus.COMPLETE,
                        turnFixture().historyArray("messages").map(StoredChatMessage::decode),
                    )
                h.model.accept(receipt, account)
                assertEquals(
                    listOf(102L, 101L, 100L),
                    h.model.state.value.messages.items
                        .map { it.id },
                )
                stale.succeed(listOf(message(99, pending.target.sessionId)))
                stale.completed.await()
                yield()
                assertEquals(
                    listOf(102L, 101L, 100L),
                    h.model.state.value.messages.items
                        .map { it.id },
                )
                h.model.accept(receipt.copy(messages = emptyList()), account.copy(revision = account.revision + 1))
                assertEquals(
                    listOf(102L, 101L, 100L),
                    h.model.state.value.messages.items
                        .map { it.id },
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `new draft target does not require a fabricated server message`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                h.conversations().succeed(emptyList())
                val target = ChatTarget("new-session")
                h.model.openConversation(target)
                val read = h.messages()
                assertEquals(target.sessionId, read.sessionId)
                assertEquals(
                    target,
                    h.model.state.value.selected
                        ?.target,
                )
                read.succeed(emptyList())
                awaitHistory { h.model.state.value.messages.loaded }
                assertTrue(
                    h.model.state.value.messages.items
                        .isEmpty(),
                )
                assertTrue(
                    h.model.state.value.conversations.items
                        .isEmpty(),
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `empty and failed initial loads are distinct and retryable`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.model.refreshConversations()
                assertTrue(
                    h.gateway.conversationReads
                        .tryReceive()
                        .isFailure,
                )
                h.login()
                assertEquals(HistoryLoad.REFRESH, h.model.state.value.conversations.loading)
                val first = h.conversations()
                h.model.bindAccount(h.session.state.value)
                h.model.refreshConversations()
                yield()
                assertTrue(
                    h.gateway.conversationReads
                        .tryReceive()
                        .isFailure,
                )
                first.response.completeExceptionally(IOException("synthetic-token-must-not-leak"))
                awaitHistory { h.model.state.value.conversations.failure != null }
                assertFalse(h.model.state.value.conversations.loaded)
                assertFalse(
                    h.model.state.value
                        .toString()
                        .contains("synthetic-token"),
                )
                h.model.refreshConversations()
                h.conversations().succeed(emptyList())
                awaitHistory { h.model.state.value.conversations.loaded }
                assertNull(h.model.state.value.conversations.failure)
                assertTrue(
                    h.model.state.value.conversations.items
                        .isEmpty(),
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `pagination preserves cursor deduplicates and retains newer summaries`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                val cursor = HistoryCursor(100, 90)
                h.conversations().succeed(listOf(summary(100, "a"), summary(90, "b")), cursor)
                awaitHistory { h.model.state.value.conversations.loaded }
                h.model.loadMoreConversations()
                val more = h.conversations()
                assertEquals(cursor, more.cursor)
                h.model.loadMoreConversations()
                yield()
                assertTrue(
                    h.gateway.conversationReads
                        .tryReceive()
                        .isFailure,
                )
                more.succeed(listOf(summary(80, "a", "旧内容"), summary(70, "c")))
                awaitHistory { h.model.state.value.conversations.loading == null }
                assertEquals(
                    listOf("a", "b", "c"),
                    h.model.state.value.conversations.items
                        .map { it.sessionId },
                )
                assertEquals(
                    100L,
                    h.model.state.value.conversations.items
                        .first()
                        .lastMessageId,
                )
                h.model.loadMoreConversations()
                yield()
                assertTrue(
                    h.gateway.conversationReads
                        .tryReceive()
                        .isFailure,
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `more failure retains items and retry repeats the original cursor`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                val cursor = HistoryCursor(100, 90)
                h.conversations().succeed(listOf(summary(90)), cursor)
                awaitHistory { h.model.state.value.conversations.loaded }
                h.model.loadMoreConversations()
                h.conversations().response.completeExceptionally(IOException("offline"))
                awaitHistory { h.model.state.value.conversations.failure != null }
                assertEquals(
                    HistoryLoad.MORE,
                    h.model.state.value.conversations.failure
                        ?.operation,
                )
                assertEquals(listOf(summary(90)), h.model.state.value.conversations.items)
                h.model.loadMoreConversations()
                val retry = h.conversations()
                assertEquals(cursor, retry.cursor)
                retry.succeed(listOf(summary(80)))
                awaitHistory { h.model.state.value.conversations.loading == null }
                assertEquals(2, h.model.state.value.conversations.items.size)
            } finally {
                h.close()
            }
        }

    @Test
    fun `refresh invalidates pending more and starts a fresh window`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                h.conversations().succeed(listOf(summary(90)), HistoryCursor(100, 90))
                awaitHistory { h.model.state.value.conversations.loaded }
                h.model.loadMoreConversations()
                val old = h.conversations()
                h.model.refreshConversations()
                val refresh = h.conversations()
                assertNull(refresh.cursor)
                refresh.succeed(listOf(summary(110)))
                awaitHistory { h.model.state.value.conversations.loading == null }
                old.succeed(listOf(summary(80)))
                old.completed.await()
                yield()
                assertEquals(listOf(summary(110)), h.model.state.value.conversations.items)
                assertNull(h.model.state.value.conversations.failure)
            } finally {
                h.close()
            }
        }

    @Test
    fun `switching conversation and closing reject late results and errors`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                h.conversations().succeed(listOf(summary(100, "a"), summary(90, "b")))
                awaitHistory { h.model.state.value.conversations.loaded }
                h.model.selectConversation("unknown")
                assertNull(h.model.state.value.selected)
                h.model.selectConversation("a")
                val old = h.messages()
                assertEquals("a", old.sessionId)
                h.model.selectConversation("b")
                val current = h.messages()
                assertTrue(
                    h.model.state.value.messages.items
                        .isEmpty(),
                )
                current.succeed(listOf(message(90, "b")))
                awaitHistory { h.model.state.value.messages.loaded }
                old.response.completeExceptionally(IOException("old failure"))
                old.completed.await()
                yield()
                assertEquals(listOf(message(90, "b")), h.model.state.value.messages.items)
                assertNull(h.model.state.value.messages.failure)
                h.model.refreshMessages()
                val closing = h.messages()
                h.model.closeConversation()
                closing.succeed(listOf(message(90, "b")))
                closing.completed.await()
                yield()
                assertNull(h.model.state.value.selected)
                assertTrue(
                    h.model.state.value.messages.items
                        .isEmpty(),
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `message pages merge by id and refresh failure preserves the visible history`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                h.conversations().succeed(listOf(summary(100, "a")))
                awaitHistory { h.model.state.value.conversations.loaded }
                h.model.selectConversation("a")
                h.messages().succeed(listOf(message(100, "a"), message(90, "a")), HistoryCursor(100, 90))
                awaitHistory { h.model.state.value.messages.loaded }
                h.model.loadMoreMessages()
                val next = h.messages()
                assertEquals(HistoryCursor(100, 90), next.cursor)
                next.succeed(listOf(message(90, "a"), message(80, "a")))
                awaitHistory { h.model.state.value.messages.loading == null }
                assertEquals(
                    listOf(100L, 90L, 80L),
                    h.model.state.value.messages.items
                        .map { it.id },
                )
                h.model.refreshMessages()
                h.messages().response.completeExceptionally(IOException("offline"))
                awaitHistory { h.model.state.value.messages.failure != null }
                assertEquals(
                    HistoryLoad.REFRESH,
                    h.model.state.value.messages.failure
                        ?.operation,
                )
                assertEquals(3, h.model.state.value.messages.items.size)
            } finally {
                h.close()
            }
        }

    @Test
    fun `account switch clears data and an old 401 cannot sign out the new account`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                h.conversations().succeed(listOf(summary(100, "shared")))
                awaitHistory { h.model.state.value.conversations.loaded }
                h.model.selectConversation("shared")
                val old = h.messages()
                val previous = h.session.state.value
                h.model.clear()
                assertEquals(ChatLibraryState(), h.model.state.value)
                h.session.logout()
                h.login(2)
                val fresh = h.conversations()
                assertEquals("synthetic-2", fresh.token)
                h.model.bindAccount(previous)
                fresh.succeed(listOf(summary(100, "shared", "账号二")))
                awaitHistory { h.model.state.value.conversations.loaded }
                old.response.completeExceptionally(HttpFailure(401, null, "old", null))
                old.completed.await()
                yield()
                assertEquals(2L, (h.session.state.value as SessionState.SignedIn).user.id)
                assertEquals(
                    "账号二",
                    h.model.state.value.conversations.items
                        .single()
                        .preview,
                )
                assertNull(h.model.state.value.selected)
                assertTrue(
                    h.model.state.value.messages.items
                        .isEmpty(),
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `current 401 clears history even before the application observer runs`() =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                h.conversations().response.completeExceptionally(HttpFailure(401, null, "expired", null))
                awaitHistory { h.model.state.value.account == null }
                assertEquals(SessionState.SignedOut(expired = true), h.session.state.value)
                assertEquals(ChatLibraryState(), h.model.state.value)
            } finally {
                h.close()
            }
        }

    @Test
    fun `closed model drops a late success and cannot restart`() =
        runBlocking {
            val h = HistoryHarness(this)
            h.login()
            val pending = h.conversations()
            h.close()
            pending.succeed(listOf(summary(100)))
            pending.completed.await()
            h.model.bindAccount(h.session.state.value)
            h.model.refreshConversations()
            yield()
            assertEquals(ChatLibraryState(), h.model.state.value)
            assertTrue(
                h.gateway.conversationReads
                    .tryReceive()
                    .isFailure,
            )
        }
}
