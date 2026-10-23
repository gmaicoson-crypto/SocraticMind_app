package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.IOException

class ChatActionsControllerTest {
    @Test
    fun `unconsumed turn receipt and stale leases cannot open mutation gate`(): Unit =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.begin().events.close()
                h.resolve(next(h.gateway.statuses))
                val account = checkNotNull(h.model.state.value.account)
                assertNull(h.model.reserveHistoryMutation(account))
                h.model.acknowledge(checkNotNull(h.model.state.value.receipt))
                val first = checkNotNull(h.model.reserveHistoryMutation(account))
                assertFalse(h.model.state.value.canSend)
                h.model.releaseHistoryMutation(first)
                val second = checkNotNull(h.model.reserveHistoryMutation(account))
                h.model.releaseHistoryMutation(first)
                assertTrue(h.model.state.value.changingHistory)
                h.model.releaseHistoryMutation(second)
                assertTrue(h.model.state.value.editable)
            } finally {
                h.close()
            }
        }

    @Test
    fun `current unauthorized mutation clears presentation and never applies result`(): Unit =
        runBlocking {
            val h = ActionsHarness(this)
            try {
                h.login()
                h.model.rename("main")
                h.model.editTitle("标题")
                h.model.confirm()
                next(h.gateway.calls).response.completeExceptionally(HttpFailure(401, null, "expired", null))
                awaitHistory { h.model.state.value.account == null }
                assertTrue(h.session.state.value is SessionState.SignedOut)
                assertNull(h.model.state.value.dialog)
                assertNull(
                    h.history.model.state.value.selected
                        ?.title,
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `rename blocks sending and late summaries without losing draft`(): Unit =
        runBlocking {
            val h = ActionsHarness(this)
            try {
                h.login()
                h.history.model.refreshConversations()
                val stale = h.history.conversations()
                h.model.rename("main")
                h.model.editTitle("🙂".repeat(41))
                h.model.confirm()
                assertFalse(h.model.state.value.canConfirm)
                assertEquals(0, h.gateway.count)
                h.model.editTitle("手动标题")
                h.model.confirm()
                h.model.confirm()
                val write = next(h.gateway.calls)
                assertFalse(h.turn.state.value.editable)
                h.turn.send("标准")
                h.turn.select(ChatTarget("other"))
                h.turn.edit("覆盖草稿")
                assertTrue(
                    h.turnGateway.streams
                        .tryReceive()
                        .isFailure,
                )
                assertEquals(
                    "main",
                    h.turn.state.value.target
                        ?.sessionId,
                )
                assertEquals("未发送的草稿", h.turn.state.value.draft)
                write.response.complete(manualTitle())
                awaitHistory { !h.model.state.value.busy }
                stale.succeed(listOf(summary(104, "main")))
                awaitHistory { stale.completed.isCompleted }
                yield()
                assertEquals(
                    "手动标题",
                    h.history.model.state.value.selected
                        ?.title,
                )
                assertEquals(
                    "手动标题",
                    h.history.model.state.value.conversations.items
                        .first()
                        .title,
                )
                assertTrue(h.turn.state.value.editable)
                assertEquals(1, h.gateway.count)
            } finally {
                h.close()
            }
        }

    @Test
    fun `session deletion requires confirmation and clears only the deleted target`(): Unit =
        runBlocking {
            val h = ActionsHarness(this)
            try {
                h.login()
                h.model.deleteSession("main")
                h.model.cancelDialog()
                yield()
                assertEquals(0, h.gateway.count)
                assertNotNull(h.history.model.state.value.selected)
                h.history.model.refreshMessages()
                val stale = h.history.messages()
                h.model.deleteSession("main")
                assertTrue((h.model.state.value.dialog as ChatAction.DeleteSession).discardsDraft)
                h.model.confirm()
                val write = next(h.gateway.calls)
                h.model.cancelDialog()
                assertTrue(h.model.state.value.busy)
                write.response.complete(null)
                awaitHistory { !h.model.state.value.busy }
                assertNull(h.history.model.state.value.selected)
                assertNull(h.turn.state.value.target)
                assertEquals("", h.turn.state.value.draft)
                assertEquals(
                    listOf("other"),
                    h.history.model.state.value.conversations.items
                        .map { it.sessionId },
                )
                stale.succeed(listOf(message(104, "main")))
                awaitHistory { stale.completed.isCompleted }
                yield()
                assertTrue(
                    h.history.model.state.value.messages.items
                        .isEmpty(),
                )
                h.history.conversations().succeed(listOf(summary(90, "other")))
            } finally {
                h.close()
            }
        }

    @Test
    fun `batch deletion removes confirmed IDs and invalidates stale reads`(): Unit =
        runBlocking {
            val h = ActionsHarness(this)
            try {
                h.login()
                h.model.selectMessages()
                h.model.toggleMessage(999)
                h.model.toggleMessage(103)
                h.model.toggleMessage(101)
                assertEquals(setOf(101L, 103L), h.model.state.value.selectedIds)
                h.history.model.refreshMessages()
                val stale = h.history.messages()
                h.model.deleteSelectedMessages()
                h.model.confirm()
                val write = next(h.gateway.calls)
                assertEquals(listOf(101L, 103L), write.ids)
                write.response.complete(null)
                awaitHistory { !h.model.state.value.busy }
                assertEquals(
                    listOf(104L, 102L),
                    h.history.model.state.value.messages.items
                        .map { it.id },
                )
                assertEquals("未发送的草稿", h.turn.state.value.draft)
                assertNull(h.model.state.value.selectionSessionId)
                stale.succeed(listOf(message(103, "main")))
                awaitHistory { stale.completed.isCompleted }
                yield()
                assertEquals(
                    listOf(104L, 102L),
                    h.history.model.state.value.messages.items
                        .map { it.id },
                )
                h.history.messages().succeed(listOf(message(104, "main"), message(102, "main")))
                h.history.conversations().succeed(listOf(summary(104, "main")))
            } finally {
                h.close()
            }
        }

    @Test
    fun `failed mutations preserve intent and require explicit retry`(): Unit =
        runBlocking {
            val h = ActionsHarness(this)
            try {
                h.login()
                h.model.rename("main")
                h.model.editTitle("重试标题")
                h.model.confirm()
                next(h.gateway.calls).response.completeExceptionally(IOException("uncertain response"))
                awaitHistory { !h.model.state.value.busy }
                assertEquals("重试标题", (h.model.state.value.dialog as ChatAction.Rename).title)
                assertNotNull(h.model.state.value.notice)
                assertTrue(h.turn.state.value.editable)
                assertNull(
                    h.history.model.state.value.selected
                        ?.title,
                )
                yield()
                assertEquals(1, h.gateway.count)
                h.model.confirm()
                next(h.gateway.calls).response.complete(manualTitle("重试标题"))
                awaitHistory { !h.model.state.value.busy }
                assertEquals(2, h.gateway.count)
                assertEquals(
                    "重试标题",
                    h.history.model.state.value.selected
                        ?.title,
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `active turn cannot be modified`(): Unit =
        runBlocking {
            val h = ActionsHarness(this)
            try {
                h.login()
                h.model.deleteSession("main")
                h.turn.send("标准")
                next(h.turnGateway.streams)
                h.model.confirm()
                yield()
                assertFalse(h.model.state.value.busy)
                assertEquals(0, h.gateway.count)
                assertNotNull(h.model.state.value.notice)
                h.model.cancelDialog()
                h.model.rename("main")
                assertNull(h.model.state.value.dialog)
            } finally {
                h.close()
            }
        }

    @Test
    fun `late old account results cannot mutate or unlock the next account`(): Unit =
        runBlocking {
            for (unauthorized in listOf(false, true)) {
                val h = ActionsHarness(this)
                try {
                    h.login()
                    h.model.rename("main")
                    h.model.editTitle("旧标题")
                    h.model.confirm()
                    val old = next(h.gateway.calls)
                    h.login(2)
                    h.model.rename("main")
                    h.model.editTitle("新标题")
                    h.model.confirm()
                    val current = next(h.gateway.calls)
                    if (unauthorized) {
                        old.response.completeExceptionally(HttpFailure(401, null, "old", null))
                    } else {
                        old.response.complete(manualTitle("旧标题"))
                    }
                    awaitHistory { old.completed.isCompleted }
                    yield()
                    assertTrue(h.model.state.value.busy)
                    assertTrue(h.turn.state.value.changingHistory)
                    assertEquals(2L, (h.session.state.value as SessionState.SignedIn).user.id)
                    assertNull(
                        h.history.model.state.value.selected
                            ?.title,
                    )
                    current.response.complete(manualTitle("新标题"))
                    awaitHistory { !h.model.state.value.busy }
                    assertEquals(
                        "新标题",
                        h.history.model.state.value.selected
                            ?.title,
                    )
                } finally {
                    h.close()
                }
            }
        }

    @Test
    fun `selection is bounded and refreshed membership is checked again`(): Unit =
        runBlocking {
            val h = ActionsHarness(this)
            try {
                h.login()
                h.history.model.refreshMessages()
                h.history.messages().succeed((201L downTo 102L).map { message(it, "main") }, HistoryCursor(201, 102))
                awaitHistory { h.history.model.state.value.messages.loading == null }
                h.history.model.loadMoreMessages()
                h.history.messages().succeed(listOf(message(101, "main")))
                awaitHistory { h.history.model.state.value.messages.items.size == 101 }
                h.model.selectMessages()
                (101L..201L).forEach(h.model::toggleMessage)
                assertEquals(100, h.model.state.value.selectedIds.size)
                assertNotNull(h.model.state.value.notice)
                h.model.deleteSelectedMessages()
                h.history.model.refreshMessages()
                h.history.messages().succeed(listOf(message(201, "main")))
                awaitHistory { h.history.model.state.value.messages.loading == null }
                h.model.confirm()
                yield()
                assertEquals(0, h.gateway.count)
                assertNotNull(h.model.state.value.notice)
                h.model.cancelDialog()
                h.model.deleteSelectedMessages()
                assertTrue(
                    h.model.state.value.selectedIds
                        .isEmpty(),
                )
                assertNull(h.model.state.value.dialog)
            } finally {
                h.close()
            }
        }

    @Test
    fun `deleting another conversation preserves selected draft and empty drafts cannot be managed`(): Unit =
        runBlocking {
            val h = ActionsHarness(this)
            try {
                h.login()
                assertFalse(h.model.canManage("unknown"))
                h.model.deleteSession("other")
                h.model.confirm()
                next(h.gateway.calls).response.complete(null)
                awaitHistory { !h.model.state.value.busy }
                assertEquals(
                    "main",
                    h.turn.state.value.target
                        ?.sessionId,
                )
                assertEquals("未发送的草稿", h.turn.state.value.draft)
                h.history.conversations().succeed(listOf(summary(104, "main").copy(title = "自动标题")))
                awaitHistory {
                    h.history.model.state.value.selected
                        ?.title == "自动标题"
                }
                h.history.model.openConversation(ChatTarget("empty"))
                h.turn.select(ChatTarget("empty"))
                h.history.messages().succeed(emptyList())
                awaitHistory { h.history.model.state.value.messages.loaded }
                assertFalse(h.model.canManage("empty"))
                h.model.rename("empty")
                assertNull(h.model.state.value.dialog)
            } finally {
                h.close()
            }
        }
}
