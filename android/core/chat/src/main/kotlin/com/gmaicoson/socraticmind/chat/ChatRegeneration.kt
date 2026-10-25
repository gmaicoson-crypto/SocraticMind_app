package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Eligibility from loaded history; the server still arbitrates source changes and concurrent questions. */
class ChatRegeneration private constructor(
    val account: HistoryAccount,
    val target: ChatTarget,
    val answerId: Long,
    val input: String,
    val context: ChatRequestContext,
) {
    companion object {
        fun from(history: ChatLibraryState): ChatRegeneration? {
            val account = history.account ?: return null
            val target = history.selected?.target ?: return null
            val page = history.messages
            if (!page.loaded || page.loading != null || page.failure != null) return null
            val question = page.items.filter { it.role == "user" }.maxByOrNull { it.id } ?: return null
            val answer = page.items.filter { it.role == "ai" }.maxByOrNull { it.id } ?: return null
            if (answer.id <= question.id || answer.attachments.isNotEmpty() ||
                listOf(question, answer).any { !supports(it, target) }
            ) {
                return null
            }
            return try {
                val requestKind = kind(question)
                require(kind(answer) == requestKind)
                answer.metadata?.let {
                    if (it.containsKey("user_message_id")) {
                        require(it.historyLong("user_message_id") == question.id)
                    }
                }
                val metadata = question.metadata ?: JsonObject(emptyMap())
                val quote = optionalString(metadata, "quote")
                val source =
                    if (metadata["quote_source_id"] == null || metadata["quote_source_id"] == JsonNull) {
                        null
                    } else {
                        metadata.historyLong("quote_source_id")
                    }
                val context = ChatRequestContext(requestKind, quote, source, attachments(question))
                context.validate(question.content, target)
                ChatRegeneration(account, target, answer.id, question.content, context)
            } catch (_: IllegalArgumentException) {
                null
            }
        }

        internal fun rejected(error: HttpFailure): Boolean =
            when (error.code) {
                "CHAT_REGENERATE_INVALID", "CHAT_REGENERATE_NOT_LATEST" -> error.status in setOf(400, 409)
                "CHAT_QUOTE_INVALID" -> error.status == 400
                "ATTACHMENT_NOT_FOUND" -> error.status == 404
                "ATTACHMENT_SCOPE_MISMATCH" -> error.status == 422
                else -> false
            }

        private fun kind(message: StoredChatMessage): ChatKind {
            val metadata = message.metadata ?: return ChatKind.QA
            if (!metadata.containsKey("kind")) return ChatKind.QA
            val value = metadata.historyString("kind")
            return requireNotNull(ChatKind.entries.singleOrNull { it.wireValue == value })
        }

        private fun optionalString(
            metadata: JsonObject,
            key: String,
        ): String? = if (metadata[key] == null || metadata[key] == JsonNull) null else metadata.historyString(key)

        private fun attachments(question: StoredChatMessage): List<String> {
            val raw = question.metadata?.get("attachment_snapshot")
            val snapshots =
                if (raw == null) {
                    JsonArray(emptyList())
                } else {
                    raw as? JsonArray
                        ?: throw IllegalArgumentException("Invalid attachment snapshot")
                }
            require(snapshots.size <= 9 && snapshots.size == question.attachments.size)
            return snapshots.mapIndexed { index, element ->
                val snapshot = element.historyObject()
                val summary = question.attachments[index]
                val id = snapshot.historyString("id")
                require(id == summary.historyString("id"))
                val revision = snapshot.historyLong("revision")
                require(revision > 0 && revision == summary.historyLong("revision"))
                require(coverage(snapshot) == coverage(summary))
                id
            }
        }

        private fun coverage(value: JsonObject): kotlinx.serialization.json.JsonElement {
            val coverage = requireNotNull(value["accepted_coverage"])
            require(coverage == JsonNull || coverage is JsonObject)
            return coverage
        }

        private fun supports(
            message: StoredChatMessage,
            target: ChatTarget,
        ): Boolean {
            if (message.messageType != "chat" || message.sessionId != target.sessionId ||
                message.nodeKey != target.nodeKey || message.mode != target.mode.wireValue ||
                (message.topicId ?: 0) != target.topicId
            ) {
                return false
            }
            val status = message.metadata?.get("status") ?: return true
            return status in listOf("complete", "failed", "interrupted").map(::JsonPrimitive)
        }
    }
}
