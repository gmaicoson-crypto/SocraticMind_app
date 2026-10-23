package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

internal fun suggestionFixture() =
    Json
        .parseToJsonElement(
            Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve("chat-suggestions.json")),
        ).historyObject()

class ChatSuggestionsApiContractTest {
    private val data = suggestionFixture()
    private val target = ChatTarget(data.getValue("target").historyObject().historyString("session_id"))
    private val exclude = data.historyArray("exclude").map { (it as JsonPrimitive).content }

    @Test
    fun `normal topic empty and fallback responses preserve context and repeated Unicode exclusions`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatSuggestionsApi(transport)
                    assertEquals(
                        ChatSuggestions.decode(data.getValue("result")),
                        api.suggestions("suggestions-contract", target, exclude, null),
                    )
                    assertEquals(
                        ChatSuggestions.decode(data.getValue("fallback")),
                        api.suggestions("suggestions-fallback", target, exclude, null),
                    )
                    assertTrue(api.suggestions("suggestions-empty", target, exclude, null).items.isEmpty())
                    assertEquals(
                        SuggestionSource.AI,
                        api
                            .suggestions(
                                "suggestions-topic",
                                target.copy(mode = ChatMode.SOCRATIC, topicId = 7, nodeKey = "节点 /+🙂"),
                                exclude,
                                "model /+🙂",
                            ).source,
                    )
                }
            }
        }

    @Test
    fun `malformed responses and unbounded inputs fail closed`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatSuggestionsApi(transport)
                    for (case in listOf("source", "duplicate", "blank", "type", "many", "long", "budget")) {
                        assertTrue(
                            runCatching { api.suggestions("suggestions-$case", target, exclude, null) }.isFailure,
                        )
                    }
                    for (invalid in listOf(List(25) { "x$it" }, listOf(" "), listOf("🙂".repeat(5001)))) {
                        assertTrue(
                            runCatching { api.suggestions("suggestions-contract", target, invalid, null) }
                                .exceptionOrNull() is IllegalArgumentException,
                        )
                    }
                    assertTrue(runCatching { api.suggestions("suggestions-contract", target, exclude, " ") }.isFailure)
                }
            }
        }

    @Test
    fun `authorization configuration and service errors remain explicit`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatSuggestionsApi(transport)
                    for ((token, status) in listOf(
                        "expired" to 401,
                        "suggestions-configuration" to 422,
                        "suggestions-unavailable" to 503,
                    )) {
                        val error = runCatching { api.suggestions(token, target, exclude, null) }.exceptionOrNull()
                        assertTrue(error is HttpFailure && error.status == status)
                    }
                }
            }
        }
}
