package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import kotlinx.serialization.json.JsonPrimitive

enum class ChatTurnPhase { RESTORING, READY, PREPARING, SENDING, VERIFYING, STOPPING, UNRESOLVED, STORAGE_FAILED }

data class ChatTurnReceipt(
    val pending: PendingChatTurn,
    val status: ChatTurnStatus?,
    val messages: List<StoredChatMessage>,
) {
    val replacedMessageId: Long? get() = pending.regenerateMessageId?.takeIf { status == ChatTurnStatus.COMPLETE }
    val historyMessages: List<StoredChatMessage> get() =
        if (pending.regenerateMessageId != null && status != ChatTurnStatus.COMPLETE) {
            messages.filter { it.role == "user" }
        } else {
            messages
        }

    fun retains(message: StoredChatMessage): Boolean {
        if (message.id == replacedMessageId) return false
        if (message.role == "ai" &&
            message.metadata?.get("request_id") == JsonPrimitive(pending.requestId)
        ) {
            return false
        }
        if (pending.regenerateMessageId == null || status == ChatTurnStatus.COMPLETE ||
            message.role != "ai"
        ) {
            return true
        }
        return messages.none { it.role == "ai" && it.id == message.id }
    }
}

data class ChatTurnState(
    val account: HistoryAccount? = null,
    val target: ChatTarget? = null,
    val phase: ChatTurnPhase = ChatTurnPhase.RESTORING,
    val draft: String = "",
    val pending: PendingChatTurn? = null,
    val submitted: String = "",
    val partial: String = "",
    val ids: ChatMessageIds? = null,
    val notice: String? = null,
    val receipt: ChatTurnReceipt? = null,
) {
    val editable: Boolean get() = account != null && phase == ChatTurnPhase.READY && pending == null
    val canSend: Boolean get() =
        editable && receipt == null && target != null && draft.isNotBlank() &&
            characterCount <= 5000
    val canRegenerate: Boolean get() = editable && receipt == null && target != null
    val characterCount: Int get() = draft.codePointCount(0, draft.length)
    val canStop: Boolean
        get() =
            pending != null &&
                phase in setOf(ChatTurnPhase.SENDING, ChatTurnPhase.VERIFYING, ChatTurnPhase.UNRESOLVED)
    val canVerify: Boolean get() = phase in setOf(ChatTurnPhase.UNRESOLVED, ChatTurnPhase.STORAGE_FAILED)

    /** History may expose the current provisional row before msg_ids or during process recovery. */
    fun showsInHistory(message: StoredChatMessage): Boolean {
        val reference = pending ?: return true
        if (reference.regenerateMessageId != null && message.role == "user") return true
        return message.id != ids?.ai && message.id != ids?.user &&
            message.metadata?.get("request_id") != JsonPrimitive(reference.requestId)
    }
}

/** Bounds retained live text. Only server status plus stored history can produce a receipt. */
internal class ChatTurnBuffer {
    private val text = StringBuilder()
    private var bytes = 0
    private var terminal = false
    var ids: ChatMessageIds? = null
        private set

    fun accept(event: ChatEvent) {
        when (event) {
            is ChatEvent.Text -> {
                require(!terminal) { "Text after terminal state" }
                bytes += event.delta.toByteArray(Charsets.UTF_8).size
                require(bytes <= 512 * 1024) { "Live text budget exceeded" }
                text.append(event.delta)
            }

            is ChatEvent.MessageIds -> {
                val next = ChatMessageIds(event.user, event.ai)
                require(ids == null || ids == next) { "Message IDs changed" }
                ids = next
            }

            is ChatEvent.RequestState -> {
                val status = ChatTurnStatus.decode(event.status)
                require(!terminal || status.terminal) { "Nonterminal state after completion" }
                terminal = status.terminal
            }

            is ChatEvent.Failure, is ChatEvent.Extension, ChatEvent.Done -> {
                Unit
            }
        }
    }

    fun content(): String = text.toString()
}
