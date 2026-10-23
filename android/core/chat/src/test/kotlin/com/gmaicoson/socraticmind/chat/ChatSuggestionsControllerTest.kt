package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import kotlinx.serialization.json.JsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.IOException

class ChatSuggestionsControllerTest {
    @Test
    fun `new conversation uses shared local starters and explicit refresh avoids all shown suggestions`() =
        withSuggestions { h ->
            h.replace(emptyList())
            h.model.setActive(true)
            val shown = h.model.state.value.items
            val expected =
                suggestionFixture()
                    .getValue("defaults")
                    .historyObject()
                    .historyArray("normal_new")
                    .take(12)
                    .map { (it as JsonPrimitive).content }
            assertEquals(expected, shown)
            assertEquals(0, h.gateway.count)
            h.model.refresh()
            val read = h.gateway.next()
            assertEquals(shown, read.exclude)
            read.response.complete(ChatSuggestions(shown, SuggestionSource.FALLBACK))
            awaitHistory { !h.model.state.value.loading }
            assertTrue(
                h.model.state.value.items
                    .none { it in shown },
            )
            assertEquals(SuggestionSource.LOCAL, h.model.state.value.source)
        }

    @Test
    fun `current context loads once and revisiting reuses memory cache`() =
        withSuggestions { h ->
            h.model.setActive(true)
            h.gateway.next().succeed("上下文追问")
            awaitHistory { !h.model.state.value.loading }
            h.base.turn.edit("草稿变化")
            yield()
            assertEquals(1, h.gateway.count)
            h.select("other")
            h.gateway.next().succeed("另一会话")
            awaitHistory { !h.model.state.value.loading }
            h.select("main")
            awaitHistory { h.model.state.value.items == listOf("上下文追问") }
            assertEquals(2, h.gateway.count)
        }

    @Test
    fun `context changes reject late results even when visible suggestion text is identical`() =
        withSuggestions { h ->
            h.model.setActive(true)
            val old = h.gateway.next()
            val context = checkNotNull(h.model.state.value.context)
            val text =
                h.model.state.value.items
                    .first()
            h.select("other")
            val fresh = h.gateway.next()
            h.model.choose(text, context, "标准")
            assertEquals("", h.base.turn.state.value.draft)
            assertNull(h.base.turn.state.value.pending)
            old.succeed("旧会话秘密")
            old.completed.await()
            yield()
            assertFalse(
                h.model.state.value.items
                    .contains("旧会话秘密"),
            )
            fresh.succeed("新会话建议")
            awaitHistory { !h.model.state.value.loading }
            assertEquals(listOf("新会话建议"), h.model.state.value.items)
        }

    @Test
    fun `same message identity with changed content invalidates cached context`() =
        withSuggestions { h ->
            h.model.setActive(true)
            h.gateway.next().succeed("旧内容建议")
            awaitHistory { !h.model.state.value.loading }
            val before = checkNotNull(h.model.state.value.context)
            h.replace(listOf(suggestionMessage(104, "main", "更新后的合成话题")))
            val read = h.gateway.next()
            assertNotEquals(
                before.version,
                h.model.state.value.context
                    ?.version,
            )
            read.succeed("新内容建议")
            awaitHistory { !h.model.state.value.loading }
        }

    @Test
    fun `visibility and model changes cancel reads without accepting late results`() =
        withSuggestions { h ->
            h.model.setActive(true)
            val old = h.gateway.next()
            h.model.setActive(false)
            old.succeed("后台迟到")
            old.completed.await()
            yield()
            assertFalse(h.model.state.value.enabled)
            assertFalse(
                h.model.state.value.items
                    .contains("后台迟到"),
            )
            h.model.setActive(true)
            val resumed = h.gateway.next()
            h.model.setModel("second-model")
            val changed = h.gateway.next()
            assertEquals("second-model", changed.model)
            resumed.succeed("旧模型")
            changed.succeed("新模型")
            awaitHistory { !h.model.state.value.loading }
            assertEquals(listOf("新模型"), h.model.state.value.items)
        }

    @Test
    fun `failure is explicit with local followups and retry remains user initiated`() =
        withSuggestions { h ->
            h.model.setActive(true)
            h.gateway
                .next()
                .response
                .completeExceptionally(IOException("offline"))
            awaitHistory { !h.model.state.value.loading }
            assertEquals(SuggestionSource.LOCAL, h.model.state.value.source)
            assertTrue(
                h.model.state.value.notice!!
                    .contains("暂不可用"),
            )
            assertTrue(
                h.model.state.value.items
                    .first()
                    .contains("刚才"),
            )
            h.base.turn.edit("typing")
            yield()
            assertEquals(1, h.gateway.count)
            h.model.refresh()
            h.gateway.next().succeed("恢复后的建议")
            awaitHistory { !h.model.state.value.loading }
            assertEquals(SuggestionSource.AI, h.model.state.value.source)
        }

    @Test
    fun `suggested send confirms draft replacement and reuses one durable request`() =
        withSuggestions { h ->
            h.model.setActive(true)
            h.gateway.next().succeed("建议文本")
            awaitHistory { !h.model.state.value.loading }
            h.base.turn.edit("保留的草稿")
            val context = checkNotNull(h.model.state.value.context)
            h.model.choose("建议文本", context, "标准")
            assertEquals("保留的草稿", h.base.turn.state.value.draft)
            assertNull(h.base.turn.state.value.pending)
            h.model.cancelChoice()
            assertNull(h.model.state.value.choice)
            h.model.choose("建议文本", context, "标准")
            h.model.confirmChoice("标准")
            h.model.confirmChoice("标准")
            val stream =
                withTimeout(2000) {
                    h.base.turnGateway.streams
                        .receive()
                }
            assertEquals("建议文本", stream.request.input)
            assertEquals(stream.request.pending, stream.saved)
            h.model.choose("建议文本", context, "标准")
            assertTrue(
                h.base.turnGateway.streams
                    .tryReceive()
                    .isFailure,
            )
        }

    @Test
    fun `refresh after canceled draft confirmation excludes the displayed suggestions`() =
        withSuggestions { h ->
            h.model.setActive(true)
            val old = h.gateway.next()
            val shown = h.model.state.value.items
            val context = checkNotNull(h.model.state.value.context)
            h.base.turn.edit("保留的草稿")
            h.model.choose(shown.first(), context, "标准")
            h.model.cancelChoice()
            h.model.refresh()
            val fresh = h.gateway.next()
            assertEquals(shown, fresh.exclude)
            old.succeed("取消前的建议")
            old.completed.await()
            fresh.succeed("新一批建议")
            awaitHistory { !h.model.state.value.loading }
            assertEquals(listOf("新一批建议"), h.model.state.value.items)
            assertEquals("保留的草稿", h.base.turn.state.value.draft)
            assertNull(h.base.turn.state.value.pending)
        }

    @Test
    fun `edited drafts and mutations reject pending or stale sends`() =
        withSuggestions { h ->
            h.model.setActive(true)
            h.gateway.next().succeed("建议")
            awaitHistory { !h.model.state.value.loading }
            val context = checkNotNull(h.model.state.value.context)
            h.base.turn.edit("草稿A")
            h.model.choose("建议", context, "标准")
            h.base.turn.edit("草稿B")
            h.model.confirmChoice("标准")
            assertEquals("草稿B", h.base.turn.state.value.draft)
            assertNull(h.base.turn.state.value.pending)
            h.base.model.deleteSession("main")
            h.base.model.confirm()
            withTimeout(2000) {
                h.base.gateway.calls
                    .receive()
            }
            h.model.choose("建议", context, "标准")
            assertEquals("草稿B", h.base.turn.state.value.draft)
            assertNull(h.base.turn.state.value.pending)
        }

    @Test
    fun `old account success and unauthorized responses cannot affect new login`() {
        for (unauthorized in listOf(false, true)) {
            withSuggestions { h ->
                h.model.setActive(true)
                val old = h.gateway.next()
                h.login(2)
                val fresh = h.gateway.next()
                assertEquals("synthetic-2", fresh.token)
                if (unauthorized) {
                    old.response.completeExceptionally(
                        HttpFailure(401, null, "old", null),
                    )
                } else {
                    old.succeed("账号一")
                }
                old.completed.await()
                yield()
                fresh.succeed("账号二")
                awaitHistory { !h.model.state.value.loading }
                assertEquals(2L, (h.base.session.state.value as SessionState.SignedIn).user.id)
                assertEquals(listOf("账号二"), h.model.state.value.items)
            }
        }
    }

    @Test
    fun `current unauthorized clears suggestions before host observers`() =
        withSuggestions { h ->
            h.model.setActive(true)
            h.gateway
                .next()
                .response
                .completeExceptionally(HttpFailure(401, null, "expired", null))
            awaitHistory { h.model.state.value.context == null }
            h.model.setActive(true)
            assertEquals(ChatSuggestionsState(), h.model.state.value)
            assertEquals(SessionState.SignedOut(expired = true), h.base.session.state.value)
        }

    @Test
    fun `cache bounds evict by entries and bytes without persisting fallback`() =
        withSuggestions { h ->
            val context =
                checkNotNull(ChatSuggestionContext.from(h.base.history.model.state.value, h.base.turn.state.value))
            val cache = ChatSuggestionsCache()
            repeat(
                31,
            ) { cache.put(context.copy(version = "$it"), ChatSuggestions(listOf("建议$it"), SuggestionSource.AI)) }
            assertEquals(30, cache.count)
            assertNull(cache.get(context.copy(version = "0")))
            cache.clear()
            repeat(
                15,
            ) {
                cache.put(
                    context.copy(version = "$it"),
                    ChatSuggestions(listOf("🙂".repeat(1200)), SuggestionSource.AI),
                )
            }
            assertEquals(13, cache.count)
            assertNull(cache.get(context.copy(version = "1")))
            cache.put(context, ChatSuggestions(listOf("备用"), SuggestionSource.FALLBACK))
            assertNull(cache.get(context))
        }

    private fun withSuggestions(body: suspend (SuggestionsHarness) -> Unit): Unit =
        runBlocking {
            val h = SuggestionsHarness(this)
            try {
                h.login()
                body(h)
            } finally {
                h.close()
            }
        }
}
