package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.AuthGrant
import com.gmaicoson.socraticmind.auth.AuthUser
import com.gmaicoson.socraticmind.auth.SessionGateway
import com.gmaicoson.socraticmind.auth.SessionStore
import com.gmaicoson.socraticmind.auth.TokenVault
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield

internal class HistoryRead<T>(
    val token: String,
    val cursor: HistoryCursor?,
    val sessionId: String? = null,
) {
    val response = CompletableDeferred<ChatHistoryPage<T>>()
    val completed = CompletableDeferred<Unit>()

    // Deliberately ignores cancellation to exercise stale-result guards, not just cooperative fakes.
    suspend fun result(): ChatHistoryPage<T> =
        withContext(NonCancellable) {
            try {
                response.await()
            } finally {
                completed.complete(Unit)
            }
        }

    fun succeed(
        items: List<T>,
        cursor: HistoryCursor? = null,
    ) {
        response.complete(ChatHistoryPage(items, cursor?.snapshotId ?: 100, cursor))
    }
}

internal class QueuedHistoryGateway : ChatHistoryGateway {
    private val pending = mutableListOf<CompletableDeferred<*>>()
    val conversationReads = Channel<HistoryRead<ConversationSummary>>(Channel.UNLIMITED)
    val messageReads = Channel<HistoryRead<StoredChatMessage>>(Channel.UNLIMITED)

    override suspend fun conversations(
        token: String,
        mode: ChatMode,
        limit: Int,
        cursor: HistoryCursor?,
    ): ChatHistoryPage<ConversationSummary> {
        check(mode == ChatMode.NORMAL && limit == 30)
        val read = HistoryRead<ConversationSummary>(token, cursor)
        pending.add(read.response)
        conversationReads.send(read)
        return read.result()
    }

    override suspend fun messages(
        token: String,
        sessionId: String,
        limit: Int,
        cursor: HistoryCursor?,
    ): ChatHistoryPage<StoredChatMessage> {
        check(limit == 30)
        val read = HistoryRead<StoredChatMessage>(token, cursor, sessionId)
        pending.add(read.response)
        messageReads.send(read)
        return read.result()
    }

    fun releasePending() {
        pending.forEach { it.completeExceptionally(CancellationException("test cleanup")) }
    }
}

internal class HistoryHarness(
    scope: CoroutineScope,
) {
    private var userId = 1L
    private var saved: String? = null

    private fun user() = AuthUser(userId, "User$userId", "u$userId@example.test", "", "", "", 5, "标准")

    val session =
        SessionStore(
            object : SessionGateway {
                override suspend fun login(
                    email: String,
                    password: String,
                ) = AuthGrant("synthetic-$userId", user())

                override suspend fun register(
                    username: String,
                    email: String,
                    password: String,
                    code: String,
                ) = login(email, password)

                override suspend fun profile(token: String) = user()
            },
            object : TokenVault {
                override fun read() = saved

                override fun write(token: String) {
                    saved = token
                }

                override fun clear() {
                    saved = null
                }
            },
        )
    val gateway = QueuedHistoryGateway()
    val titles = QueuedTitlesGateway()
    val model = ChatLibraryController(session, gateway, scope, titles, titlePollDelays = List(7) { 0 })

    suspend fun login(id: Long = 1) {
        if (session.state.value == com.gmaicoson.socraticmind.auth.SessionState.Uninitialized) session.restore()
        userId = id
        session.login("u$id@example.test", "synthetic-password")
        model.bindAccount(session.state.value)
    }

    suspend fun conversations() = withTimeout(2_000) { gateway.conversationReads.receive() }

    suspend fun messages() = withTimeout(2_000) { gateway.messageReads.receive() }

    fun close() {
        model.close()
        gateway.releasePending()
        titles.releasePending()
    }
}

internal suspend fun awaitHistory(condition: () -> Boolean) =
    withTimeout(2_000) {
        while (!condition()) yield()
    }

internal fun summary(
    id: Long,
    session: String = "s$id",
    preview: String = "内容$id",
) = ConversationSummary(
    session,
    "normal",
    null,
    "__normal__",
    id,
    "assistant",
    preview,
    null,
    null,
    null,
)

internal fun message(
    id: Long,
    session: String,
) = StoredChatMessage(
    id,
    "assistant",
    "消息$id",
    "__normal__",
    "normal",
    null,
    session,
    "text",
    null,
    null,
    emptyList(),
)
