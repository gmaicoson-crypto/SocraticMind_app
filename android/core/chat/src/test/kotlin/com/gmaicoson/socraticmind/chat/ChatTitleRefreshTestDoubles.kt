package com.gmaicoson.socraticmind.chat

import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withTimeout

internal data class TitleRead(
    val ids: List<String>,
    val read: HistoryRead<ChatTitle>,
)

internal class QueuedTitlesGateway : ChatTitlesGateway {
    private val queue = Channel<TitleRead>(Channel.UNLIMITED)
    private val all = mutableListOf<TitleRead>()
    val count: Int get() = all.size

    override suspend fun titles(
        token: String,
        sessionIds: List<String>,
    ): List<ChatTitle> {
        val call = TitleRead(sessionIds, HistoryRead(token, null))
        all.add(call)
        queue.send(call)
        return call.read.result().items
    }

    suspend fun next() = withTimeout(2000) { queue.receive() }

    fun releasePending() {
        all.forEach { it.read.succeed(emptyList()) }
    }
}

internal fun title(
    id: String,
    status: ChatTitleStatus = ChatTitleStatus.READY,
    text: String? = "标题$id",
    retry: Boolean = false,
) = ChatTitle(id, text, status, retry)
