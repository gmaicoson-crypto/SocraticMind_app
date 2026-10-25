package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
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
    val regenerateMessageId: Long? = null,
) {
    init {
        require(ownerId > 0 && requestId.matches(Regex("[A-Za-z0-9_-]{1,100}")))
        require(regenerateMessageId == null || regenerateMessageId > 0)
    }
}

data class ChatTurnRequest(
    val pending: PendingChatTurn,
    val input: String,
    val style: String,
    val context: ChatRequestContext = ChatRequestContext(),
    val model: String? = null,
) {
    init {
        context.validate(input, pending.target)
        requireModelId(model)
        require(style.isNotBlank() && style.codePointCount(0, style.length) <= 20)
    }

    fun json(): JsonObject =
        buildJsonObject {
            put("request_id", pending.requestId)
            put("session_id", pending.target.sessionId)
            put("mode", pending.target.mode.wireValue)
            put("node_key", pending.target.nodeKey)
            put("topic_id", pending.target.topicId)
            put("kind", context.kind.wireValue)
            put("user_input", input)
            put("ai_style", style)
            model?.let { put("model", it) }
            pending.regenerateMessageId?.let { put("regenerate_message_id", it) }
            context.quoteText?.let { put("quote_text", it) }
            context.quoteSourceId?.let { put("quote_source_id", it) }
            if (context.attachmentIds.isNotEmpty()) {
                put("attachment_ids", JsonArray(context.attachmentIds.map(::JsonPrimitive)))
            }
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
