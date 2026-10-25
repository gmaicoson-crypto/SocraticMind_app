package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.ChatEvent
import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

internal fun modelFixture() =
    Json
        .parseToJsonElement(
            Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve("model-selection.json")),
        ).historyObject()

class ChatModelApiContractTest {
    @Test
    fun `directory keeps configuration identity and does not infer first as default`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatModelApi(transport)
                    val expected = ChatModelCatalog.decode(modelFixture().getValue("catalog"))
                    val actual = api.catalog("models-contract")
                    assertEquals(expected.models, actual.models)
                    assertEquals(
                        1,
                        actual.models
                            .map { it.model }
                            .distinct()
                            .size,
                    )
                    assertNotEquals(modelFixture().historyString("default_id"), actual.models.first().id)
                    assertTrue(api.catalog("models-empty").models.isEmpty())
                    assertEquals(listOf("é", "e\u0301"), api.catalog("models-unicode").models.map { it.id })
                }
            }
        }

    @Test
    fun `default environment and custom choices reach both stream and suggestions unchanged`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    for (item in modelFixture().historyArray("requests")) {
                        val row = item.historyObject()
                        val expected = row.getValue("request").historyObject()
                        val target = ChatTarget(expected.historyString("session_id"))
                        val request =
                            ChatTurnRequest(
                                PendingChatTurn(1, target, expected.historyString("request_id")),
                                expected.historyString("user_input"),
                                expected.historyString("ai_style"),
                                model = expected["model"]?.let { expected.historyString("model") },
                            )
                        assertEquals(expected, request.json())
                        val token = "models-${row.historyString("name") }"
                        val events = ChatTurnApi(transport).stream(token, request).toList()
                        assertEquals("你好，世界🙂", events.filterIsInstance<ChatEvent.Text>().joinToString("") { it.delta })
                        assertEquals(
                            listOf("合成模型建议🙂"),
                            ChatSuggestionsApi(transport)
                                .suggestions(
                                    token,
                                    target,
                                    emptyList(),
                                    request.model,
                                ).items,
                        )
                    }
                    assertFalse(turnRequest().json().containsKey("model"))
                }
            }
        }

    @Test
    fun `malformed or oversized catalogs and invalid request IDs fail closed`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatModelApi(transport)
                    for (case in listOf(
                        "duplicate",
                        "many",
                        "id",
                        "name",
                        "model",
                        "blank",
                        "type",
                        "source",
                        "budget",
                    )) {
                        assertTrue(runCatching { api.catalog("models-$case") }.isFailure, case)
                    }
                }
            }
            for (id in listOf("", " ", "🙂".repeat(101))) {
                assertTrue(runCatching { turnRequest().copy(model = id) }.isFailure)
            }
            assertEquals("🙂".repeat(100), turnRequest().copy(model = "🙂".repeat(100)).model)
        }

    @Test
    fun `authentication failures and typed model rejection retain status and code`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    for ((token, status) in listOf("expired" to 401, "models-failure" to 503)) {
                        val failure = runCatching { ChatModelApi(transport).catalog(token) }.exceptionOrNull()
                        assertTrue(failure is HttpFailure && failure.status == status)
                    }
                    val failure =
                        runCatching { ChatTurnApi(transport).stream("models-unavailable", turnRequest()).toList() }
                            .exceptionOrNull()
                    assertTrue(
                        failure is HttpFailure && failure.status == 422 && failure.code == "LLM_MODEL_UNAVAILABLE",
                    )
                }
            }
        }
}
