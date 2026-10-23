package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Shared by normal and future node conversations; a draft does not invent a stored message ID. */
data class ChatTarget(
    val sessionId: String,
    val mode: ChatMode = ChatMode.NORMAL,
    val nodeKey: String = "__normal__",
    val topicId: Long = 0,
) {
    init {
        requireSessionId(sessionId)
        require(sessionId == sessionId.trim() && nodeKey == nodeKey.trim())
        require(nodeKey.isNotBlank() && nodeKey.codePointCount(0, nodeKey.length) <= 200 && topicId >= 0)
    }
}

/** Contains recovery identifiers only, never a prompt, access token or model credential. */
data class PendingChatTurn(
    val ownerId: Long,
    val target: ChatTarget,
    val requestId: String,
) {
    init {
        require(ownerId > 0 && requestId.matches(Regex("[A-Za-z0-9_-]{1,100}")))
    }
}

data class ChatTurnRequest(
    val pending: PendingChatTurn,
    val input: String,
    val style: String,
) {
    init {
        require(input.isNotBlank() && input.codePointCount(0, input.length) <= 5000)
        require(style.isNotBlank() && style.codePointCount(0, style.length) <= 20)
    }

    fun json(): JsonObject =
        buildJsonObject {
            put("request_id", pending.requestId)
            put("session_id", pending.target.sessionId)
            put("mode", pending.target.mode.wireValue)
            put("node_key", pending.target.nodeKey)
            put("topic_id", pending.target.topicId)
            put("kind", "qa")
            put("user_input", input)
            put("ai_style", style)
        }
}

enum class ChatTurnStatus(
    val wireValue: String,
) {
    GENERATING("generating"),
    COMPLETE("complete"),
    FAILED("failed"),
    INTERRUPTED("interrupted"),
    ;

    val terminal: Boolean get() = this != GENERATING

    companion object {
        fun decode(value: String): ChatTurnStatus = entries.single { it.wireValue == value }
    }
}

data class ChatMessageIds(
    val user: Long,
    val ai: Long,
) {
    init {
        require(user > 0 && ai > 0 && user != ai)
    }
}

data class RemoteChatTurn(
    val status: ChatTurnStatus,
    val ids: ChatMessageIds?,
)

interface ChatTurnGateway {
    fun stream(
        token: String,
        request: ChatTurnRequest,
    ): Flow<ChatEvent>

    suspend fun status(
        token: String,
        pending: PendingChatTurn,
    ): RemoteChatTurn

    suspend fun cancel(
        token: String,
        pending: PendingChatTurn,
    ): RemoteChatTurn

    suspend fun messages(
        token: String,
        pending: PendingChatTurn,
        ids: ChatMessageIds,
    ): List<StoredChatMessage>
}

interface ChatTurnJournal {
    suspend fun read(ownerId: Long): PendingChatTurn?

    /** Must be durable before the caller may POST. Existing different requests cannot be overwritten. */
    suspend fun save(pending: PendingChatTurn)

    /** Compare the request ID before clearing, so stale cleanup cannot remove a later turn. */
    suspend fun clear(pending: PendingChatTurn)
}
