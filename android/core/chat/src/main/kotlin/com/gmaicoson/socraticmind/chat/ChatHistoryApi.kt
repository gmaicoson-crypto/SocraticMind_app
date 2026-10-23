package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpTransport

/** Call through SessionStore.authenticated; this adapter never owns or persists credentials. */
class ChatHistoryApi(
    private val transport: HttpTransport,
) : ChatHistoryGateway {
    override suspend fun conversations(
        token: String,
        mode: ChatMode,
        limit: Int,
        cursor: HistoryCursor?,
    ): ChatHistoryPage<ConversationSummary> {
        val value =
            transport.request(
                "GET",
                "api/chat/sessions",
                bearer = token,
                query = pageQuery(limit, cursor) + ("mode" to mode.wireValue),
            )
        val page = decodeHistoryPage(value, limit, cursor, ConversationSummary::decode) { it.lastMessageId }
        require(page.items.all { it.mode == mode.wireValue }) { "Unexpected conversation mode" }
        require(
            page.items
                .map { it.sessionId }
                .distinct()
                .size == page.items.size,
        ) { "Duplicate conversations" }
        return page
    }

    override suspend fun messages(
        token: String,
        sessionId: String,
        limit: Int,
        cursor: HistoryCursor?,
    ): ChatHistoryPage<StoredChatMessage> {
        requireSessionId(sessionId)
        val value =
            transport.request(
                "GET",
                "api/chat/session-messages",
                bearer = token,
                query = pageQuery(limit, cursor) + ("session_id" to sessionId),
            )
        val page = decodeHistoryPage(value, limit, cursor, StoredChatMessage::decode) { it.id }
        require(page.items.all { it.sessionId == sessionId }) { "Unexpected message session" }
        return page
    }

    /** Exact lookup through the existing bounded endpoint; never substitutes a neighbouring message. */
    suspend fun message(
        token: String,
        sessionId: String,
        id: Long,
    ): StoredChatMessage? {
        requireSessionId(sessionId)
        require(id > 0)
        val value =
            transport.request(
                "GET",
                "api/chat/session-messages",
                bearer = token,
                query = mapOf("session_id" to sessionId, "snapshot_id" to id.toString(), "limit" to "1"),
            )
        val page = decodeHistoryPage(value, 1, null, StoredChatMessage::decode) { it.id }
        require(page.snapshotId == id && page.items.all { it.sessionId == sessionId })
        return page.items.singleOrNull()?.takeIf { it.id == id }
    }

    private fun pageQuery(
        limit: Int,
        cursor: HistoryCursor?,
    ): Map<String, String> {
        require(limit in 1..100) { "History page limit must be 1...100" }
        return buildMap {
            put("limit", limit.toString())
            cursor?.let {
                put("snapshot_id", it.snapshotId.toString())
                put("before_id", it.beforeId.toString())
            }
        }
    }
}
