package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

private fun actionsFixture() =
    Json
        .parseToJsonElement(
            Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve("chat-actions.json")),
        ).historyObject()

class ChatActionsApiContractTest {
    @Test
    fun `bulk title reads encode repeated IDs and validate returned subsets`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatActionsApi(transport)
                    val data = actionsFixture()
                    val ids =
                        data
                            .historyArray(
                                "batch_ids",
                            ).map { (it as kotlinx.serialization.json.JsonPrimitive).content }
                    val expected = data.historyArray("batch_titles").map(ChatTitle::decode)
                    assertEquals(expected, api.titles("actions-batch", ids))
                    for (case in listOf("duplicate", "unrequested")) {
                        assertTrue(runCatching { api.titles("actions-batch-$case", ids) }.isFailure)
                    }
                    for (invalid in listOf(emptyList(), listOf("x", "x"), listOf(""), (1..101).map { "s$it" })) {
                        assertTrue(
                            runCatching {
                                api.titles(
                                    "actions-batch",
                                    invalid,
                                )
                            }.exceptionOrNull() is IllegalArgumentException,
                        )
                    }
                }
            }
        }

    @Test
    fun `title rename and deletes preserve opaque identity and exact JSON`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatActionsApi(transport)
                    val data = actionsFixture()
                    val sid = data.historyString("session_id")
                    val expected = ChatTitle.decode(data.getValue("renamed"))
                    assertEquals(expected, api.title("actions-contract", sid))
                    assertNull(api.title("actions-empty", sid))
                    assertEquals(
                        expected,
                        api.rename(
                            "actions-contract",
                            sid,
                            data.getValue("rename").historyObject().historyString("title"),
                        ),
                    )
                    assertEquals(2L, api.deleteSession("actions-contract", sid))
                    assertEquals(2L, api.deleteMessages("actions-contract", listOf(101, 102)))
                }
            }
        }

    @Test
    fun `invalid title results never become successful reads or renames`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatActionsApi(transport)
                    val data = actionsFixture()
                    val sid = data.historyString("session_id")
                    val title = data.getValue("renamed").historyObject().historyString("title")
                    for (row in data.historyArray("invalid_titles")) {
                        val token = "actions-${row.historyObject().historyString("id")}"
                        assertTrue(runCatching { api.title(token, sid) }.exceptionOrNull() is IllegalArgumentException)
                        assertTrue(
                            runCatching { api.rename(token, sid, title) }.exceptionOrNull() is IllegalArgumentException,
                        )
                    }
                    assertTrue(runCatching { api.title("actions-duplicate", sid) }.isFailure)
                }
            }
        }

    @Test
    fun `invalid counts and local mutation inputs fail closed`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatActionsApi(transport)
                    val sid = actionsFixture().historyString("session_id")
                    for (case in listOf("negative", "excessive", "string", "boolean")) {
                        assertTrue(runCatching { api.deleteMessages("actions-$case", listOf(101, 102)) }.isFailure)
                    }
                    for (ids in listOf(emptyList(), listOf(0L), listOf(1L, 1L), (1L..101L).toList())) {
                        assertTrue(
                            runCatching {
                                api.deleteMessages(
                                    "actions-contract",
                                    ids,
                                )
                            }.exceptionOrNull() is IllegalArgumentException,
                        )
                    }
                    for (title in listOf(" ", "🙂".repeat(41))) {
                        assertTrue(
                            runCatching {
                                api.rename(
                                    "actions-contract",
                                    sid,
                                    title,
                                )
                            }.exceptionOrNull() is IllegalArgumentException,
                        )
                    }
                    assertTrue(runCatching { api.deleteSession("actions-contract", " padded ") }.isFailure)
                }
            }
        }

    @Test
    fun `unauthorized missing and unavailable remain explicit HTTP failures`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatActionsApi(transport)
                    val data = actionsFixture()
                    val sid = data.historyString("session_id")
                    val title = data.getValue("renamed").historyObject().historyString("title")
                    for ((token, status) in listOf(
                        "expired" to 401,
                        "actions-missing" to 404,
                        "actions-unsupported" to 405,
                        "actions-unavailable" to 503,
                    )) {
                        val errors =
                            listOf(
                                runCatching { api.title(token, sid) }.exceptionOrNull(),
                                runCatching { api.rename(token, sid, title) }.exceptionOrNull(),
                                runCatching { api.deleteSession(token, sid) }.exceptionOrNull(),
                                runCatching { api.deleteMessages(token, listOf(101, 102)) }.exceptionOrNull(),
                            )
                        assertTrue(errors.all { it is HttpFailure && it.status == status })
                    }
                }
            }
        }
}
