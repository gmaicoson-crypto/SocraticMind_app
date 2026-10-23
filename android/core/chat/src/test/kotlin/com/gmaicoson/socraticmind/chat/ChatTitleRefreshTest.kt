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

class ChatTitleRefreshTest {
    @Test
    fun `batch shrinks to jobs still pending and updates selected title`() =
        withTitles { h ->
            h.model.refreshConversations()
            h.conversations().succeed(listOf(summary(4, "a"), summary(3, "b"), summary(2, "c"), summary(1, "missing")))
            awaitHistory { h.model.state.value.conversations.loading == null }
            h.model.selectConversation("a")
            h.messages().succeed(emptyList())
            h.model.setTitlePollingActive(true)
            val first = h.titles.next()
            assertEquals(listOf("a", "b", "c", "missing"), first.ids)
            first.read.succeed(
                listOf(
                    title("a"),
                    title("b", ChatTitleStatus.RUNNING, null),
                    title("c", ChatTitleStatus.FAILED, null, true),
                ),
            )
            val second = h.titles.next()
            assertEquals(listOf("b", "c"), second.ids)
            assertEquals(
                "标题a",
                h.model.state.value.selected
                    ?.title,
            )
            second.read.succeed(listOf(title("b", ChatTitleStatus.FAILED, null), title("c")))
            awaitHistory { !h.model.state.value.refreshingTitles }
            assertTrue(
                h.model.state.value.titleNotice!!
                    .contains("失败"),
            )
            assertEquals(2, h.titles.count)
            assertEquals(4, h.model.state.value.conversations.items.size)
        }

    @Test
    fun `eight read budget ends and only an explicit refresh starts another cycle`() =
        withTitles { h ->
            h.model.setTitlePollingActive(true)
            repeat(8) {
                h.titles
                    .next()
                    .read
                    .succeed(listOf(title("a", ChatTitleStatus.PENDING, null)))
            }
            awaitHistory { !h.model.state.value.refreshingTitles }
            assertTrue(
                h.model.state.value.titleNotice!!
                    .contains("稍后刷新"),
            )
            repeat(3) { h.model.setTitlePollingActive(true) }
            yield()
            assertEquals(8, h.titles.count)
            h.model.refreshConversations()
            h.conversations().succeed(listOf(summary(2, "a")))
            h.titles
                .next()
                .read
                .succeed(emptyList())
            awaitHistory { !h.model.state.value.refreshingTitles }
            assertEquals(9, h.titles.count)
            assertNull(h.model.state.value.titleNotice)
        }

    @Test
    fun `hidden view cancels reads and late result cannot replace resumed cycle`() =
        withTitles { h ->
            assertEquals(0, h.titles.count)
            h.model.setTitlePollingActive(true)
            val old = h.titles.next()
            h.model.setTitlePollingActive(false)
            assertFalse(h.model.state.value.refreshingTitles)
            h.model.setTitlePollingActive(true)
            val fresh = h.titles.next()
            old.read.succeed(listOf(title("a", text = "过期")))
            old.read.completed.await()
            yield()
            assertNull(
                h.model.state.value.conversations.items
                    .single()
                    .title,
            )
            assertTrue(h.model.state.value.refreshingTitles)
            fresh.read.succeed(listOf(title("a", text = "最新")))
            awaitHistory { !h.model.state.value.refreshingTitles }
            assertEquals(
                "最新",
                h.model.state.value.conversations.items
                    .single()
                    .title,
            )
        }

    @Test
    fun `manual rename fences a late automatic title`() =
        withTitles { h ->
            h.model.selectConversation("a")
            h.messages().succeed(emptyList())
            h.model.setTitlePollingActive(true)
            val old = h.titles.next()
            h.model.accept(
                ChatLibraryChange.Renamed(title("a", ChatTitleStatus.MANUAL, "手动")),
                checkNotNull(h.model.state.value.account),
            )
            old.read.succeed(listOf(title("a", text = "自动旧值")))
            old.read.completed.await()
            yield()
            assertEquals(
                "手动",
                h.model.state.value.selected
                    ?.title,
            )
            assertEquals(
                "manual",
                h.model.state.value.conversations.items
                    .single()
                    .titleStatus,
            )
            assertFalse(h.model.state.value.refreshingTitles)
        }

    @Test
    fun `deletion fences late titles without resurrecting a summary`() =
        withTitles { h ->
            h.model.setTitlePollingActive(true)
            val old = h.titles.next()
            h.model.accept(ChatLibraryChange.DeletedSession("a"), checkNotNull(h.model.state.value.account))
            h.conversations().succeed(emptyList())
            old.read.succeed(listOf(title("a")))
            old.read.completed.await()
            yield()
            awaitHistory { h.model.state.value.conversations.loading == null }
            assertTrue(
                h.model.state.value.conversations.items
                    .isEmpty(),
            )
            assertFalse(h.model.state.value.refreshingTitles)
        }

    @Test
    fun `fresh conversation response wins over an earlier title read`() =
        withTitles { h ->
            h.model.setTitlePollingActive(true)
            val old = h.titles.next()
            h.model.refreshConversations()
            h.conversations().succeed(listOf(summary(2, "a").copy(title = "另一设备手动", titleStatus = "manual")))
            awaitHistory { h.model.state.value.conversations.loading == null }
            old.read.succeed(listOf(title("a", text = "旧生成")))
            old.read.completed.await()
            yield()
            assertEquals(
                "另一设备手动",
                h.model.state.value.conversations.items
                    .single()
                    .title,
            )
            assertEquals(1, h.titles.count)
        }

    @Test
    fun `account revision rejects old success and unauthorized results`() {
        for (unauthorized in listOf(false, true)) {
            withTitles { h ->
                h.model.setTitlePollingActive(true)
                val old = h.titles.next()
                h.model.clear()
                h.session.logout()
                h.login(2)
                h.conversations().succeed(listOf(summary(2, "a")))
                val fresh = h.titles.next()
                assertEquals("synthetic-2", fresh.read.token)
                if (unauthorized) {
                    old.read.response.completeExceptionally(HttpFailure(401, null, "old", null))
                } else {
                    old.read.succeed(listOf(title("a", text = "账号一")))
                }
                old.read.completed.await()
                yield()
                assertEquals(2L, (h.session.state.value as SessionState.SignedIn).user.id)
                assertNull(
                    h.model.state.value.conversations.items
                        .single()
                        .title,
                )
                fresh.read.succeed(listOf(title("a", text = "账号二")))
                awaitHistory { !h.model.state.value.refreshingTitles }
                assertEquals(
                    "账号二",
                    h.model.state.value.conversations.items
                        .single()
                        .title,
                )
            }
        }
    }

    @Test
    fun `current unauthorized read clears history before app observation`() =
        withTitles { h ->
            h.model.setTitlePollingActive(true)
            h.titles
                .next()
                .read.response
                .completeExceptionally(HttpFailure(401, null, "expired", null))
            awaitHistory { h.model.state.value.account == null }
            assertEquals(SessionState.SignedOut(expired = true), h.session.state.value)
            assertEquals(ChatLibraryState(), h.model.state.value)
        }

    @Test
    fun `read failure stops without clearing history or retrying in the background`() =
        withTitles { h ->
            h.model.setTitlePollingActive(true)
            h.titles
                .next()
                .read.response
                .completeExceptionally(IOException("offline"))
            awaitHistory { !h.model.state.value.refreshingTitles }
            assertTrue(
                h.model.state.value.titleNotice!!
                    .contains("失败"),
            )
            assertEquals(1, h.titles.count)
            assertEquals(1, h.model.state.value.conversations.items.size)
        }

    @Test
    fun `opening and refreshing an older selected conversation keeps its title eligible`() =
        withTitles { h ->
            h.model.setTitlePollingActive(true)
            h.titles
                .next()
                .read
                .succeed(emptyList())
            awaitHistory { !h.model.state.value.refreshingTitles }
            h.model.selectConversation("a")
            h.messages().succeed(emptyList())
            awaitHistory { h.model.state.value.messages.loaded }
            val old = h.titles.next()
            h.model.refreshSelectedConversation()
            h.messages().succeed(emptyList())
            h.conversations().succeed(listOf(summary(2, "newer").copy(title = "完成", titleStatus = "ready")))
            val selected = h.titles.next()
            assertEquals(listOf("a"), selected.ids)
            old.read.succeed(listOf(title("a", text = "过期")))
            selected.read.succeed(listOf(title("a", text = "旧会话新标题")))
            awaitHistory { !h.model.state.value.refreshingTitles }
            assertEquals(
                "旧会话新标题",
                h.model.state.value.selected
                    ?.title,
            )
            assertEquals(
                listOf("newer"),
                h.model.state.value.conversations.items
                    .map { it.sessionId },
            )
        }

    @Test
    fun `candidate cap prioritizes selected and newly loaded page while retaining terminal rows`() {
        val rows =
            (1L..130L).map { summary(it, "s$it") } +
                summary(131, "ready").copy(title = "完成", titleStatus = "ready") +
                summary(132, "manual").copy(title = "手动", titleStatus = "manual")
        val state =
            ChatLibraryState(
                conversations = HistoryPageState(items = rows),
                selected = ChatConversation(ChatTarget("s1")),
            )
        val ids = state.titleCandidates(newerPageFirst = true)
        assertEquals(100, ids.size)
        assertEquals(listOf("s1", "s130", "s129"), ids.take(3))
        assertFalse(ids.contains("manual") || ids.contains("ready"))
        assertEquals(
            rows.size,
            state
                .withTitles(listOf(title("s1")))
                .conversations.items.size,
        )
    }

    private fun withTitles(body: suspend (HistoryHarness) -> Unit): Unit =
        runBlocking {
            val h = HistoryHarness(this)
            try {
                h.login()
                h.conversations().succeed(listOf(summary(1, "a")))
                awaitHistory { h.model.state.value.conversations.loaded }
                body(h)
            } finally {
                h.close()
            }
        }
}
