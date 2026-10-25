package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ChatFeedbackStateTest {
    @Test
    fun `confirmed feedback wins over live hints without retrying the request`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                val stream = h.begin()
                stream.events.send(ChatEvent.Failure("AI_QUOTA_EXCEEDED", "synthetic-private-key", false))
                stream.events.close()
                val status = next(h.gateway.statuses)
                assertNull(h.model.state.value.receipt)
                assertFalse(h.model.state.value.canSend)
                status.response.complete(
                    RemoteChatTurn(ChatTurnStatus.INTERRUPTED, ChatMessageIds(101, 102), feedbackValue("AI_TIMEOUT")),
                )
                next(
                    h.gateway.messages,
                ).response.complete(turnFixture().historyArray("messages").map(StoredChatMessage::decode))
                awaitHistory { h.model.state.value.editable }
                assertTrue(checkNotNull(h.model.state.value.notice).contains("超时"))
                assertFalse(checkNotNull(h.model.state.value.notice).contains("额度不足"))
                assertFalse(checkNotNull(h.model.state.value.notice).contains("synthetic-private-key"))
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                assertNull(h.journal.read(1))
                h.model.select(ChatTarget("different-session"))
                assertNull(h.model.state.value.notice)
                h.model.clear()
                assertNull(h.model.state.value.receipt)
            } finally {
                h.close()
            }
        }

    @Test
    fun `failed regeneration reports its hidden attempt and preserves old answer and draft`() =
        runBlocking {
            val h = TurnHarness(this)
            try {
                h.login()
                h.ready()
                h.model.edit("独立草稿")
                val messages = turnFixture().historyArray("messages").map(StoredChatMessage::decode)
                val source =
                    ChatLibraryState(
                        account = h.model.state.value.account,
                        selected = ChatConversation(turnRequest().pending.target),
                        messages = HistoryPageState(messages, loaded = true),
                    )
                h.model.regenerate(source, "标准")
                next(h.gateway.streams).events.close()
                next(
                    h.gateway.statuses,
                ).response.complete(
                    RemoteChatTurn(ChatTurnStatus.FAILED, ChatMessageIds(101, 103), feedbackValue("AI_QUOTA_EXCEEDED")),
                )
                next(h.gateway.messages).response.complete(messages.filter { it.role == "user" })
                awaitHistory { h.model.state.value.editable }
                val notice = checkNotNull(h.model.state.value.notice)
                assertTrue(notice.contains("额度不足") && notice.contains("原回答仍保留") && notice.contains("合计 59"))
                assertTrue(notice.contains(ChatAnswerFeedback.SCOPE_NOTE))
                assertEquals("独立草稿", h.model.state.value.draft)
                val receipt = checkNotNull(h.model.state.value.receipt)
                assertNull(receipt.replacedMessageId)
                assertEquals(messages, messages.filter(receipt::retains))
                assertTrue(
                    h.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `cancel recovery uses stored reason and missing messages keep the deletion notice`() {
        val messages = turnFixture().historyArray("messages").map(StoredChatMessage::decode)
        val pending = turnRequest().pending
        val stopped =
            RemoteChatTurn(ChatTurnStatus.INTERRUPTED, ChatMessageIds(101, 102), feedbackValue("USER_CANCELLED"))
        assertTrue(checkNotNull(ChatTurnOutcome.notice(pending, stopped, messages, false)).contains("已停止"))
        assertTrue(checkNotNull(ChatTurnOutcome.notice(pending, stopped, emptyList(), false)).contains("更新或删除"))
        assertTrue(checkNotNull(ChatTurnOutcome.notice(pending, stopped, messages, true)).contains("模型不可用"))
        assertNull(
            ChatTurnOutcome.notice(
                pending,
                RemoteChatTurn(ChatTurnStatus.COMPLETE, stopped.ids, stopped.feedback),
                messages,
                false,
            ),
        )
    }
}
