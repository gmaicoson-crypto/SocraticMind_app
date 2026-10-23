package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.IOException

internal class MemoryTurnJournal : ChatTurnJournal {
    val records = mutableMapOf<Long, PendingChatTurn>()
    var failRead = false
    var failSave = false
    var failAfterSave = false
    var failClear = false
    var failAfterClear = false

    override suspend fun read(ownerId: Long): PendingChatTurn? {
        if (failRead) throw IOException("read")
        return records[ownerId]
    }

    override suspend fun save(pending: PendingChatTurn) {
        if (failSave) throw IOException("write")
        check(records[pending.ownerId] == null || records[pending.ownerId] == pending)
        records[pending.ownerId] = pending
        if (failAfterSave) throw IOException("after write")
    }

    override suspend fun clear(pending: PendingChatTurn) {
        if (failClear) throw IOException("clear")
        check(records[pending.ownerId] == pending)
        records.remove(pending.ownerId)
        if (failAfterClear) throw IOException("after clear")
    }
}

internal class TurnRead<T>(
    val token: String,
    val pending: PendingChatTurn,
) {
    val response = CompletableDeferred<T>()
    val completed = CompletableDeferred<Unit>()

    suspend fun result(): T =
        withContext(NonCancellable) {
            try {
                response.await()
            } finally {
                completed.complete(Unit)
            }
        }
}

internal class TurnStream(
    val request: ChatTurnRequest,
    val saved: PendingChatTurn?,
) {
    val events = Channel<ChatEvent>(Channel.UNLIMITED)
}

internal class QueuedTurnGateway(
    private val journal: MemoryTurnJournal,
) : ChatTurnGateway {
    val streams = Channel<TurnStream>(Channel.UNLIMITED)
    val statuses = Channel<TurnRead<RemoteChatTurn>>(Channel.UNLIMITED)
    val cancels = Channel<TurnRead<RemoteChatTurn>>(Channel.UNLIMITED)
    val messages = Channel<TurnRead<List<StoredChatMessage>>>(Channel.UNLIMITED)
    private val pending = mutableListOf<CompletableDeferred<*>>()

    override fun stream(
        token: String,
        request: ChatTurnRequest,
    ) = flow {
        val read = TurnStream(request, journal.read(request.pending.ownerId))
        streams.send(read)
        for (event in read.events) emit(event)
    }

    override suspend fun status(
        token: String,
        pending: PendingChatTurn,
    ) = read(statuses, token, pending)

    override suspend fun cancel(
        token: String,
        pending: PendingChatTurn,
    ) = read(cancels, token, pending)

    override suspend fun messages(
        token: String,
        pending: PendingChatTurn,
        ids: ChatMessageIds,
    ) = read(messages, token, pending)

    private suspend fun <T> read(
        queue: Channel<TurnRead<T>>,
        token: String,
        reference: PendingChatTurn,
    ): T {
        val read = TurnRead<T>(token, reference)
        pending.add(read.response)
        queue.send(read)
        return read.result()
    }

    fun close() {
        pending.forEach { it.completeExceptionally(CancellationException("cleanup")) }
    }
}

internal class TurnHarness(
    scope: CoroutineScope,
    val journal: MemoryTurnJournal = MemoryTurnJournal(),
) {
    private val auth = HistoryHarness(scope)
    val session get() = auth.session
    val gateway = QueuedTurnGateway(journal)
    val model =
        ChatTurnController(
            session,
            gateway,
            journal,
            scope,
            requestId = { "turn-contract-id" },
            pollDelays = emptyList(),
        )

    suspend fun login(id: Long = 1) {
        auth.login(id)
        auth.conversations().succeed(emptyList())
        model.bindAccount(session.state.value)
    }

    suspend fun ready() {
        awaitHistory { model.state.value.editable }
        model.select(turnRequest().pending.target)
        model.edit(turnRequest().input)
    }

    suspend fun begin(): TurnStream {
        model.send("标准")
        return next(gateway.streams)
    }

    suspend fun resolve(
        read: TurnRead<RemoteChatTurn>,
        status: ChatTurnStatus = ChatTurnStatus.COMPLETE,
    ) {
        read.response.complete(RemoteChatTurn(status, ChatMessageIds(101, 102)))
        next(gateway.messages).response.complete(turnFixture().historyArray("messages").map(StoredChatMessage::decode))
        awaitHistory { model.state.value.phase in setOf(ChatTurnPhase.READY, ChatTurnPhase.STORAGE_FAILED) }
    }

    fun close() {
        model.close()
        gateway.close()
        auth.close()
    }
}

internal suspend fun <T> next(channel: Channel<T>): T = withTimeout(2000) { channel.receive() }
