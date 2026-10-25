package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpTransport
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Mutations inherit the transport's no-retry policy. Recovery is GET-only. */
class ChatTurnApi(
    private val transport: HttpTransport,
) : ChatTurnGateway {
    private val history = ChatHistoryApi(transport)

    override fun stream(
        token: String,
        request: ChatTurnRequest,
    ) = transport.stream("api/chat/stream", token, request.json())

    override suspend fun status(
        token: String,
        pending: PendingChatTurn,
    ): RemoteChatTurn {
        val value = transport.request("GET", "api/chat/requests/${pending.requestId}", bearer = token).historyObject()
        require(value.historyString("request_id") == pending.requestId)
        require(value.historyString("session_id") == pending.target.sessionId)
        val status = ChatTurnStatus.decode(value.historyString("status"))
        return RemoteChatTurn(status, decodeIds(value), ChatAnswerFeedback.decode(value, status))
    }

    override suspend fun cancel(
        token: String,
        pending: PendingChatTurn,
    ): RemoteChatTurn {
        val value =
            transport
                .request(
                    "POST",
                    "api/chat/cancel",
                    bearer = token,
                    json =
                        buildJsonObject {
                            put("request_id", pending.requestId)
                            put("session_id", pending.target.sessionId)
                        },
                ).historyObject()
        val status = ChatTurnStatus.decode(value.historyString("status"))
        val ids = if (value.containsKey("msg_ids")) decodeIds(value) else null
        require(status.terminal && (ids != null || status == ChatTurnStatus.INTERRUPTED))
        return RemoteChatTurn(status, ids, ChatAnswerFeedback.decode(value, status))
    }

    override suspend fun messages(
        token: String,
        pending: PendingChatTurn,
        ids: ChatMessageIds,
    ): List<StoredChatMessage> =
        listOfNotNull(
            history.message(token, pending.target.sessionId, ids.user)?.also { require(it.role == "user") },
            history.message(token, pending.target.sessionId, ids.ai)?.also { require(it.role == "ai") },
        ).also { messages ->
            require(messages.all { it.mode == pending.target.mode.wireValue && it.nodeKey == pending.target.nodeKey })
        }

    private fun decodeIds(value: JsonObject): ChatMessageIds {
        val ids = value.getValue("msg_ids").historyObject()
        return ChatMessageIds(ids.historyLong("user"), ids.historyLong("ai"))
    }
}
