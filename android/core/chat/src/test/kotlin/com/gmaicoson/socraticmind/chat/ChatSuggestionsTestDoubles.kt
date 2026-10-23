package com.gmaicoson.socraticmind.chat

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

internal class SuggestionRead(
    val token: String,
    val target: ChatTarget,
    val exclude: List<String>,
    val model: String?,
) {
    val response = CompletableDeferred<ChatSuggestions>()
    val completed = CompletableDeferred<Unit>()

    suspend fun result(): ChatSuggestions =
        withContext(NonCancellable) {
            try {
                response.await()
            } finally {
                completed.complete(Unit)
            }
        }

    fun succeed(vararg items: String) {
        response.complete(ChatSuggestions(items.toList(), SuggestionSource.AI))
    }
}

internal class QueuedSuggestionsGateway : ChatSuggestionsGateway {
    private val calls = Channel<SuggestionRead>(Channel.UNLIMITED)
    private val pending = mutableListOf<SuggestionRead>()
    val count: Int get() = pending.size

    override suspend fun suggestions(
        token: String,
        target: ChatTarget,
        exclude: List<String>,
        model: String?,
    ): ChatSuggestions {
        val read = SuggestionRead(token, target, exclude, model)
        pending.add(read)
        calls.send(read)
        return read.result()
    }

    suspend fun next() = withTimeout(2000) { calls.receive() }

    fun close() {
        pending.forEach { it.response.completeExceptionally(CancellationException("cleanup")) }
    }
}

internal class SuggestionsHarness(
    scope: CoroutineScope,
) {
    val base = ActionsHarness(scope)
    val gateway = QueuedSuggestionsGateway()
    val model = ChatSuggestionsController(base.session, gateway, base.history.model, base.turn, scope)

    suspend fun login(
        id: Long = 1,
        empty: Boolean = false,
    ) {
        base.login(id)
        base.turn.edit("")
        replace(if (empty) emptyList() else listOf(suggestionMessage(104, "main")))
    }

    suspend fun replace(rows: List<StoredChatMessage>) {
        base.history.model.refreshMessages()
        base.history.messages().succeed(rows)
        awaitHistory { base.history.model.state.value.messages.loading == null }
    }

    suspend fun select(id: String) {
        base.history.model.selectConversation(id)
        base.turn.select(
            base.history.model.state.value.selected
                ?.target,
        )
        base.history.messages().succeed(listOf(suggestionMessage(104, id)))
        awaitHistory { base.history.model.state.value.messages.loaded }
    }

    fun close() {
        model.close()
        base.close()
        gateway.close()
    }
}

internal fun suggestionMessage(
    id: Long,
    session: String,
    text: String = "合成话题$id",
) = message(id, session).copy(content = text, messageType = "chat", role = "user")
