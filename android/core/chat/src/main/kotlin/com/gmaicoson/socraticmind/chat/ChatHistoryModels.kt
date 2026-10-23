package com.gmaicoson.socraticmind.chat

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

enum class ChatMode(
    val wireValue: String,
) {
    NORMAL("normal"),
    SOCRATIC("socratic"),
}

/** Reuse the original upper bound on every older-page request. Refresh starts without a cursor. */
data class HistoryCursor(
    val snapshotId: Long,
    val beforeId: Long,
) {
    init {
        require(snapshotId > 0 && beforeId in 1..snapshotId) { "Invalid history cursor" }
    }
}

data class ChatHistoryPage<T>(
    val items: List<T>,
    val snapshotId: Long,
    val nextCursor: HistoryCursor?,
)

data class ConversationSummary(
    val sessionId: String,
    val mode: String,
    val topicId: Long?,
    val nodeKey: String,
    val lastMessageId: Long,
    val lastRole: String,
    val preview: String,
    val updatedAt: String?,
    val title: String?,
    val titleStatus: String?,
) {
    companion object {
        fun decode(value: JsonElement): ConversationSummary {
            val objectValue = value.historyObject()
            return ConversationSummary(
                sessionId = objectValue.historyString("session_id").also(::requireSessionId),
                mode = objectValue.historyString("mode"),
                topicId = objectValue.historyOptionalLong("topic_id"),
                nodeKey = objectValue.historyString("node_key"),
                lastMessageId = objectValue.historyLong("last_message_id").also { require(it > 0) },
                lastRole = objectValue.historyString("last_role"),
                preview = objectValue.historyString("preview"),
                updatedAt = objectValue.historyOptionalString("updated_at"),
                title = objectValue.historyOptionalString("title"),
                titleStatus = objectValue.historyOptionalString("title_status"),
            )
        }
    }
}

/** Retains structured learning / source / attachment additions without treating them as plain chat. */
data class StoredChatMessage(
    val id: Long,
    val role: String,
    val content: String,
    val nodeKey: String,
    val mode: String,
    val topicId: Long?,
    val sessionId: String,
    val messageType: String,
    val metadata: JsonObject?,
    val createdAt: String?,
    val attachments: List<JsonObject>,
) {
    companion object {
        fun decode(value: JsonElement): StoredChatMessage {
            val objectValue = value.historyObject()
            return StoredChatMessage(
                id = objectValue.historyLong("id").also { require(it > 0) },
                role = objectValue.historyString("role"),
                content = objectValue.historyString("content"),
                nodeKey = objectValue.historyString("node_key"),
                mode = objectValue.historyString("mode"),
                topicId = objectValue.historyOptionalLong("topic_id"),
                sessionId = objectValue.historyString("session_id").also(::requireSessionId),
                messageType = objectValue.historyString("message_type"),
                metadata = objectValue.historyOptional("metadata")?.historyObject(),
                createdAt = objectValue.historyOptionalString("created_at"),
                attachments = objectValue.historyArray("attachments").map { it.historyObject() },
            )
        }
    }
}
