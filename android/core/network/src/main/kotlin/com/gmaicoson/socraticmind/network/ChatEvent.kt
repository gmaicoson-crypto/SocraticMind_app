package com.gmaicoson.socraticmind.network

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

sealed interface ChatEvent {
    data class Text(
        val delta: String,
    ) : ChatEvent

    data class MessageIds(
        val user: Long,
        val ai: Long,
    ) : ChatEvent

    data class RequestState(
        val status: String,
    ) : ChatEvent

    data class Failure(
        val code: String,
        val message: String,
        val retryable: Boolean,
    ) : ChatEvent

    data class Extension(
        val payload: JsonObject,
    ) : ChatEvent

    data object Done : ChatEvent
}

/** Unknown additions remain available to future feature consumers, never treated as success. */
object ChatEventDecoder {
    fun decode(data: String): List<ChatEvent> {
        if (data == "[DONE]") return listOf(ChatEvent.Done)
        val payload =
            Json.parseToJsonElement(data) as? JsonObject
                ?: throw IllegalArgumentException("Chat event must be an object")
        val events = mutableListOf<ChatEvent>()
        payload["msg_ids"]?.let {
            val ids = it as? JsonObject ?: throw IllegalArgumentException("Invalid message IDs")
            events.add(ChatEvent.MessageIds(ids.positiveId("user"), ids.positiveId("ai")))
        }
        payload["text"]?.let { events.add(ChatEvent.Text(payload.string("text"))) }
        payload["request_state"]?.let {
            val state = it as? JsonObject ?: throw IllegalArgumentException("Invalid request state")
            events.add(ChatEvent.RequestState(state.string("status")))
        }
        payload["error"]?.let {
            val error = it as? JsonObject ?: throw IllegalArgumentException("Invalid error")
            val flag = error["retryable"] as? JsonPrimitive
            val retryable =
                flag?.takeUnless { value -> value.isString }?.booleanOrNull
                    ?: throw IllegalArgumentException("Invalid retryable flag")
            events.add(ChatEvent.Failure(error.string("code"), error.string("message"), retryable))
        }
        if ("type" in payload) payload.string("type")
        if (events.isEmpty() || "type" in payload) events.add(ChatEvent.Extension(payload))
        return events
    }

    private fun JsonObject.string(key: String): String {
        val value = this[key] as? JsonPrimitive
        require(value != null && value.isString) { "Invalid $key string" }
        return value.content
    }

    private fun JsonObject.positiveId(key: String): Long {
        val value = this[key] as? JsonPrimitive
        val number = value?.longOrNull
        require(value != null && !value.isString && number != null && number > 0) { "Invalid $key ID" }
        return number
    }
}
