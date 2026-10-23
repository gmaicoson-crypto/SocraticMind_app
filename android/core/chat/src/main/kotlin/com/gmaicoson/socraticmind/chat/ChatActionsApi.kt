package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpTransport
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

enum class ChatTitleStatus(
    val wireValue: String,
) {
    PENDING("pending"),
    RUNNING("running"),
    READY("ready"),
    MANUAL("manual"),
    FAILED("failed"),
}

data class ChatTitle(
    val sessionId: String,
    val title: String?,
    val status: ChatTitleStatus,
    val retryPending: Boolean,
) {
    companion object {
        fun decode(value: JsonElement): ChatTitle {
            val row = value.historyObject()
            val status =
                requireNotNull(
                    ChatTitleStatus.entries.singleOrNull {
                        it.wireValue ==
                            row.historyString("status")
                    },
                )
            val title = row.historyOptionalString("title")
            require(title == null || (title.isNotBlank() && title.codePointCount(0, title.length) <= 40))
            require(title != null || status !in setOf(ChatTitleStatus.READY, ChatTitleStatus.MANUAL))
            val retry = (row["retry_pending"] as? JsonPrimitive)?.takeUnless { it.isString }?.booleanOrNull
            require(retry != null && (!retry || status == ChatTitleStatus.FAILED))
            return ChatTitle(row.historyString("session_id").also(::requireSessionId), title, status, retry)
        }
    }
}

interface ChatActionsGateway {
    suspend fun title(
        token: String,
        sessionId: String,
    ): ChatTitle?

    suspend fun rename(
        token: String,
        sessionId: String,
        title: String,
    ): ChatTitle

    suspend fun deleteSession(
        token: String,
        sessionId: String,
    ): Long

    suspend fun deleteMessages(
        token: String,
        ids: List<Long>,
    ): Long
}

/** Authenticated, finite mutations; the common transport never automatically replays writes. */
class ChatActionsApi(
    private val transport: HttpTransport,
) : ChatActionsGateway {
    override suspend fun title(
        token: String,
        sessionId: String,
    ): ChatTitle? {
        requireSessionId(sessionId)
        val value =
            transport.request(
                "GET",
                "api/chat/session-titles",
                bearer = token,
                query = mapOf("ids" to sessionId),
            )
        val rows = value as? JsonArray ?: error("Expected titles")
        require(rows.size <= 1)
        return rows.singleOrNull()?.let(ChatTitle::decode)?.also { require(it.sessionId == sessionId) }
    }

    override suspend fun rename(
        token: String,
        sessionId: String,
        title: String,
    ): ChatTitle {
        requireSessionId(sessionId)
        require(sessionId == sessionId.trim())
        val clean = title.trim()
        require(clean.isNotEmpty() && clean.codePointCount(0, clean.length) <= 40)
        val value =
            transport.request(
                "PUT",
                "api/chat/session-titles",
                bearer = token,
                json =
                    buildJsonObject {
                        put("session_id", sessionId)
                        put("title", clean)
                    },
            )
        return ChatTitle.decode(value).also {
            require(it.sessionId == sessionId && it.status == ChatTitleStatus.MANUAL && it.title == clean)
        }
    }

    override suspend fun deleteSession(
        token: String,
        sessionId: String,
    ): Long {
        requireSessionId(sessionId)
        require(sessionId == sessionId.trim())
        return deleted(
            transport.request(
                "DELETE",
                "api/chat/session",
                bearer = token,
                json = buildJsonObject { put("session_id", sessionId) },
            ),
        )
    }

    override suspend fun deleteMessages(
        token: String,
        ids: List<Long>,
    ): Long {
        require(ids.size in 1..100 && ids.all { it > 0 } && ids.distinct().size == ids.size)
        val result =
            deleted(
                transport.request(
                    "DELETE",
                    "api/chat/messages",
                    bearer = token,
                    json = buildJsonObject { put("ids", JsonArray(ids.map(::JsonPrimitive))) },
                ),
            )
        require(result <= ids.size)
        return result
    }

    private fun deleted(value: JsonElement): Long =
        value.historyObject().historyLong("deleted").also { require(it >= 0) }
}
