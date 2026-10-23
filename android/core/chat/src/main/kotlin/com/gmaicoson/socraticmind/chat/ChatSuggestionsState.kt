package com.gmaicoson.socraticmind.chat

import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest

/** Only a bounded digest of the relevant messages enters the cache key. */
data class ChatSuggestionContext(
    val account: HistoryAccount,
    val target: ChatTarget,
    val version: String,
    val hasConversation: Boolean,
    val model: String? = null,
) {
    companion object {
        fun from(
            history: ChatLibraryState,
            turn: ChatTurnState,
            model: String? = null,
        ): ChatSuggestionContext? {
            val account = history.account ?: return null
            val target = history.selected?.target ?: return null
            if (turn.account != account || turn.target != target || !history.messages.loaded) return null
            val recent =
                history.messages.items
                    .asSequence()
                    .filter {
                        it.messageType == "chat" && it.mode == target.mode.wireValue &&
                            (target.mode != ChatMode.SOCRATIC || it.topicId == target.topicId) &&
                            it.content.isNotBlank() &&
                            (it.metadata?.get("status") ?: JsonPrimitive("complete")) ==
                            JsonPrimitive("complete")
                    }.take(6)
                    .toList()
            val digest = MessageDigest.getInstance("SHA-256")
            recent.forEach { row ->
                var start = row.content.length
                repeat(800) { if (start > 0) start = row.content.offsetByCodePoints(start, -1) }
                val suffix = row.content.substring(start)
                digest.update(
                    "${row.id}:${row.role}:${suffix.toByteArray(
                        Charsets.UTF_8,
                    ).size}:$suffix".toByteArray(Charsets.UTF_8),
                )
            }
            return ChatSuggestionContext(
                account,
                target,
                digest.digest().joinToString("") { "%02x".format(it) },
                recent.isNotEmpty(),
                model,
            )
        }
    }
}

data class ChatSuggestionChoice(
    val text: String,
    val draft: String,
)

data class ChatSuggestionsState(
    val context: ChatSuggestionContext? = null,
    val items: List<String> = emptyList(),
    val source: SuggestionSource = SuggestionSource.LOCAL,
    val enabled: Boolean = false,
    val loading: Boolean = false,
    val notice: String? = null,
    val choice: ChatSuggestionChoice? = null,
)

/** Bounded account-local LRU; no suggestion or message content is written to disk. */
internal class ChatSuggestionsCache {
    private val entries = mutableListOf<Pair<ChatSuggestionContext, ChatSuggestions>>()

    private fun bytes() = entries.sumOf { it.second.items.sumOf { text -> text.toByteArray(Charsets.UTF_8).size } }

    val count: Int get() = entries.size

    fun clear() = entries.clear()

    fun get(context: ChatSuggestionContext): ChatSuggestions? {
        val index = entries.indexOfFirst { it.first == context }
        if (index < 0) return null
        val entry = entries.removeAt(index)
        entries.add(entry)
        return entry.second
    }

    fun put(
        context: ChatSuggestionContext,
        result: ChatSuggestions,
    ) {
        if (result.source != SuggestionSource.AI || result.items.isEmpty()) return
        entries.removeAll { it.first == context }
        entries.add(context to result)
        while (entries.size > 30 || bytes() > 65536) entries.removeAt(0)
    }
}
