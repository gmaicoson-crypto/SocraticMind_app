package com.gmaicoson.socraticmind.chat

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

/** Eligibility from the latest loaded question. The server still arbitrates concurrent changes. */
class ChatRegeneration private constructor(
    val account: HistoryAccount,
    val target: ChatTarget,
    val answerId: Long,
    val input: String,
) {
    companion object {
        fun from(history: ChatLibraryState): ChatRegeneration? {
            val account = history.account ?: return null
            val target = history.selected?.target ?: return null
            val page = history.messages
            if (!page.loaded || page.loading != null || page.failure != null) return null
            val question = page.items.filter { it.role == "user" }.maxByOrNull { it.id } ?: return null
            val answer = page.items.filter { it.role == "ai" }.maxByOrNull { it.id } ?: return null
            if (answer.id <= question.id || question.content.isBlank() ||
                question.content.codePointCount(0, question.content.length) > 5000
            ) {
                return null
            }
            if (listOf(question, answer).any { !supports(it, target) }) return null
            return ChatRegeneration(account, target, answer.id, question.content)
        }

        private fun supports(
            message: StoredChatMessage,
            target: ChatTarget,
        ): Boolean {
            if (message.messageType != "chat" || message.sessionId != target.sessionId ||
                message.nodeKey != target.nodeKey || message.mode != target.mode.wireValue ||
                (message.topicId ?: 0) != target.topicId || message.attachments.isNotEmpty()
            ) {
                return false
            }
            val metadata = message.metadata ?: return true
            if (metadata["kind"] != null && metadata["kind"] != JsonPrimitive("qa")) return false
            if (metadata["status"] != null && metadata["status"] !in
                listOf("complete", "failed", "interrupted").map(::JsonPrimitive)
            ) {
                return false
            }
            // Attachment / quote requests need their own complete snapshot, never silently drop context.
            return listOf("quote", "quote_source_id").all { metadata[it] == null || metadata[it] == JsonNull } &&
                (metadata["attachment_snapshot"] == null || metadata["attachment_snapshot"] == JsonArray(emptyList()))
        }
    }
}
