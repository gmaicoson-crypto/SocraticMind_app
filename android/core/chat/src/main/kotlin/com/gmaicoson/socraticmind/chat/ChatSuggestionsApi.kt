package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpTransport
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

/** An AI response and a server fallback remain distinguishable in the UI. */
enum class SuggestionSource { AI, FALLBACK, LOCAL }

data class ChatSuggestions(
    val items: List<String>,
    val source: SuggestionSource,
) {
    init {
        require(items.size <= 12 && items.distinct().size == items.size)
        require(items.all { it.isNotBlank() && it == it.trim() && it.codePointCount(0, it.length) <= 5000 })
        require(items.sumOf { it.toByteArray(Charsets.UTF_8).size } <= 65536)
    }

    companion object {
        fun decode(value: JsonElement): ChatSuggestions {
            val row = value.historyObject()
            val source =
                when (row.historyString("source")) {
                    "ai" -> SuggestionSource.AI
                    "fallback" -> SuggestionSource.FALLBACK
                    else -> error("Unknown suggestion source")
                }
            val items =
                row.historyArray("suggestions").map {
                    requireNotNull((it as? JsonPrimitive)?.takeIf { value -> value.isString }).content
                }
            return ChatSuggestions(items, source)
        }
    }
}

interface ChatSuggestionsGateway {
    suspend fun suggestions(
        token: String,
        target: ChatTarget,
        exclude: List<String>,
        model: String?,
    ): ChatSuggestions
}

class ChatSuggestionsApi(
    private val transport: HttpTransport,
) : ChatSuggestionsGateway {
    override suspend fun suggestions(
        token: String,
        target: ChatTarget,
        exclude: List<String>,
        model: String?,
    ): ChatSuggestions {
        require(exclude.size <= 24)
        require(exclude.all { it.isNotBlank() && it.codePointCount(0, it.length) <= 5000 })
        requireModelId(model)
        val query = mutableMapOf("mode" to target.mode.wireValue, "session_id" to target.sessionId)
        if (target.mode == ChatMode.SOCRATIC && target.topicId > 0) {
            require(target.nodeKey.codePointCount(0, target.nodeKey.length) <= 100)
            query["topic_id"] = target.topicId.toString()
            query["node_key"] = target.nodeKey
        }
        model?.let { query["model"] = it }
        val excluded =
            exclude
                .map { raw ->
                    val value = raw.trim()
                    String(value.codePoints().limit(80).toArray(), 0, minOf(80, value.codePointCount(0, value.length)))
                }.distinct()
        return ChatSuggestions.decode(
            transport.request(
                "GET",
                "api/chat/suggestions",
                bearer = token,
                query = query,
                repeatedQuery = mapOf("exclude" to excluded),
            ),
        )
    }
}
