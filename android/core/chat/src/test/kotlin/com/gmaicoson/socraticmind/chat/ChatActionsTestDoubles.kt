package com.gmaicoson.socraticmind.chat

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withContext

internal class ActionWrite(
    val token: String,
    val kind: String,
    val sessionId: String?,
    val title: String? = null,
    val ids: List<Long> = emptyList(),
) {
    val response = CompletableDeferred<ChatTitle?>()
    val completed = CompletableDeferred<Unit>()

    suspend fun result(): ChatTitle? =
        withContext(NonCancellable) {
            try {
                response.await()
            } finally {
                completed.complete(Unit)
            }
        }
}

internal class QueuedActionsGateway : ChatActionsGateway {
    val calls = Channel<ActionWrite>(Channel.UNLIMITED)
    private val pending = mutableListOf<ActionWrite>()
    var count = 0
        private set

    override suspend fun title(
        token: String,
        sessionId: String,
    ): ChatTitle? = error("No per-row title polling")

    override suspend fun rename(
        token: String,
        sessionId: String,
        title: String,
    ): ChatTitle =
        checkNotNull(
            write(ActionWrite(token, "rename", sessionId, title)).result(),
        )

    override suspend fun deleteSession(
        token: String,
        sessionId: String,
    ): Long {
        write(ActionWrite(token, "session", sessionId)).result()
        return 2
    }

    override suspend fun deleteMessages(
        token: String,
        ids: List<Long>,
    ): Long {
        write(ActionWrite(token, "messages", null, ids = ids)).result()
        return ids.size.toLong()
    }

    private suspend fun write(value: ActionWrite): ActionWrite {
        count++
        pending.add(value)
        calls.send(value)
        return value
    }

    fun close() {
        pending.forEach { it.response.completeExceptionally(CancellationException("cleanup")) }
    }
}

internal class ActionsHarness(
    scope: CoroutineScope,
    onSessionDeleted: suspend (HistoryAccount, String) -> String? = { _, _ -> null },
) {
    val history = HistoryHarness(scope)
    val session get() = history.session
    val journal = MemoryTurnJournal()
    val turnGateway = QueuedTurnGateway(journal)
    val turn = ChatTurnController(session, turnGateway, journal, scope, pollDelays = emptyList())
    val gateway = QueuedActionsGateway()
    val model = ChatActionsController(session, gateway, history.model, turn, scope, onSessionDeleted)

    suspend fun login(id: Long = 1) {
        if (session.state.value is com.gmaicoson.socraticmind.auth.SessionState.SignedIn) {
            model.clear()
            history.model.clear()
            turn.clear()
            session.logout()
        }
        history.login(id)
        turn.bindAccount(session.state.value)
        model.bindAccount(session.state.value)
        history.conversations().succeed(listOf(summary(104, "main"), summary(90, "other")))
        awaitHistory { history.model.state.value.conversations.loaded && turn.state.value.editable }
        history.model.selectConversation("main")
        history.messages().succeed((104L downTo 101L).map { message(it, "main") })
        awaitHistory { history.model.state.value.messages.loaded }
        turn.select(checkNotNull(history.model.state.value.selected).target)
        turn.edit("未发送的草稿")
    }

    fun close() {
        model.close()
        turn.close()
        history.close()
        gateway.close()
        turnGateway.close()
    }
}

internal fun manualTitle(value: String = "手动标题") = ChatTitle("main", value, ChatTitleStatus.MANUAL, false)
