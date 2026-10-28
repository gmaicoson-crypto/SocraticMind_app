package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.storage.AccountFileStorage
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.File
import java.nio.file.Files

class FileChatAvatarStoreTest {
    private val preset = ChatAvatarResource.default(ChatMode.NORMAL)

    @Test
    fun `opaque Unicode identities remain distinct and duplicate records are rejected`(): Unit =
        withStore { root ->
            val store = FileChatAvatarStore(root, "scope")
            val first = "caf\u00e9"
            val second = "cafe\u0301"
            val other = ChatAvatarResource.default(ChatMode.SOCRATIC)
            store.replace(7, first, null, preset)
            store.replace(7, second, null, other)
            val reopened = FileChatAvatarStore(root, "scope").read(7)
            assertEquals(2, reopened.size)
            assertEquals(preset, reopened[first])
            assertEquals(other, reopened[second])
            val file = root.walkTopDown().single { it.extension == "json" }
            val record = Json.parseToJsonElement(file.readText()).historyObject()
            val choices = record.historyArray("choices")
            file.writeText(
                buildJsonObject {
                    record.forEach { (key, value) -> put(key, value) }
                    put("choices", JsonArray(choices + choices.first()))
                }.toString(),
            )
            assertTrue(runCatching { store.read(7) }.isFailure)
        }

    @Test
    fun `reopen preserves account endpoint and journal isolation with only paths on disk`(): Unit =
        withStore { root ->
            val store = FileChatAvatarStore(root, "scope")
            val data = avatarFixture()
            val id = data.historyString("session_id")
            val resource = ChatAvatarResource(data.historyString("upload_url"))
            store.replace(7, id, null, resource)
            store.replace(8, "other", null, preset)
            val journal = AccountFileStorage(root, "scope", "chat-turns", 4096)
            val pending = "synthetic recovery identifiers".toByteArray()
            journal.write(7, pending)
            assertEquals(mapOf(id to resource), FileChatAvatarStore(root, "scope").read(7))
            assertEquals(mapOf("other" to preset), store.read(8))
            assertTrue(FileChatAvatarStore(root, "other-scope").read(7).isEmpty())
            store.clear(7)
            assertTrue(store.read(7).isEmpty())
            assertEquals(mapOf("other" to preset), store.read(8))
            assertTrue(journal.read(7)?.contentEquals(pending) == true)
            val contents =
                root
                    .walkTopDown()
                    .filter { it.isFile }
                    .map { it.readText() }
                    .toList()
            assertTrue(
                contents.none {
                    it.contains("access_token") || it.contains("image_base64") ||
                        it.contains("user_input")
                },
            )
        }

    @Test
    fun `stale replacement or removal cannot overwrite a newer choice`(): Unit =
        withStore { root ->
            val store = FileChatAvatarStore(root, "scope")
            val next = ChatAvatarResource(ChatAvatarResource.presets(ChatMode.NORMAL)[1])
            store.replace(7, "main", null, preset)
            store.replace(7, "main", preset, next)
            for (value in listOf(null, preset)) {
                val error = runCatching { store.replace(7, "main", preset, value) }.exceptionOrNull()
                assertTrue(error is ChatAvatarException && error.failure == ChatAvatarFailure.CONFLICT)
            }
            assertEquals(next, store.read(7)["main"])
            store.replace(7, "main", next, null)
            assertTrue(store.read(7).isEmpty())
        }

    @Test
    fun `corrupt owner schema path and oversized records fail without overwrite`(): Unit =
        withStore { root ->
            val store = FileChatAvatarStore(root, "scope")
            store.replace(7, "main", null, preset)
            val file = root.walkTopDown().single { it.extension == "json" }
            val original = file.readText()
            for (bad in listOf(
                "{",
                "x".repeat(512 * 1024 + 1),
                original.replace("\"schema\":1", "\"schema\":2"),
                original.replace("\"owner_id\":7", "\"owner_id\":8"),
                original.replace(preset.path, "https://example.test/a"),
            )) {
                file.writeText(bad)
                assertTrue(runCatching { store.read(7) }.isFailure)
                assertTrue(runCatching { store.replace(7, "main", preset, null) }.isFailure)
                assertEquals(bad, file.readText())
            }
            store.clear(7)
            assertTrue(store.read(7).isEmpty())
        }

    @Test
    fun `entry capacity preserves existing choices and allows replacement and removal`(): Unit =
        withStore { root ->
            val store = FileChatAvatarStore(root, "scope")
            store.replace(7, "seed", null, preset)
            val file = root.walkTopDown().single { it.extension == "json" }
            file.writeText(
                buildJsonObject {
                    put("schema", 1)
                    put("owner_id", 7)
                    put(
                        "choices",
                        buildJsonArray {
                            repeat(1000) {
                                add(
                                    buildJsonObject {
                                        put("session_id", "session-$it")
                                        put("path", preset.path)
                                    },
                                )
                            }
                        },
                    )
                }.toString(),
            )
            val original = file.readText()
            val error = runCatching { store.replace(7, "extra", null, preset) }.exceptionOrNull()
            assertTrue(error is ChatAvatarException && error.failure == ChatAvatarFailure.CAPACITY)
            assertEquals(original, file.readText())
            val next = ChatAvatarResource.default(ChatMode.SOCRATIC)
            store.replace(7, "session-0", preset, next)
            assertEquals(1000, store.read(7).size)
            store.replace(7, "session-0", next, null)
            store.replace(7, "extra", null, preset)
            assertEquals(1000, store.read(7).size)
        }

    @Test
    fun `atomic IO budget and failed temporary write preserve previous bytes`(): Unit =
        withStore { root ->
            val io = AccountFileStorage(root, "scope", "chat-avatars", 32)
            io.write(7, "old".toByteArray())
            val file = root.walkTopDown().single { it.extension == "json" }
            assertTrue(runCatching { io.write(7, ByteArray(33)) }.isFailure)
            assertEquals("old", file.readText())
            File(file.parentFile, "7.tmp").mkdir()
            assertTrue(runCatching { io.write(7, "new".toByteArray()) }.isFailure)
            assertEquals("old", file.readText())
            val blocked = File(root, "blocked").apply { writeText("file") }
            assertTrue(runCatching { FileChatAvatarStore(blocked, "scope").replace(7, "main", null, preset) }.isFailure)
        }

    @Test
    fun `concurrent compare and replace accepts only one writer and rejects foreign uploaded references`(): Unit =
        withStore { root ->
            val store = FileChatAvatarStore(root, "scope")
            val other = ChatAvatarResource.default(ChatMode.SOCRATIC)
            val results =
                coroutineScope {
                    listOf(preset, other)
                        .map { value ->
                            async {
                                runCatching { store.replace(7, "main", null, value) }
                            }
                        }.map { it.await() }
                }
            assertEquals(1, results.count { it.isSuccess })
            assertTrue(store.read(7)["main"] in listOf(preset, other))
            val resource = ChatAvatarResource(avatarFixture().historyString("upload_url"))
            assertTrue(runCatching { store.replace(7, "different-session", null, resource) }.isFailure)
            assertTrue(
                runCatching { store.replace(8, avatarFixture().historyString("session_id"), null, resource) }.isFailure,
            )
            assertTrue(runCatching { store.replace(7, " space ", null, preset) }.isFailure)
        }

    private fun withStore(body: suspend (File) -> Unit): Unit =
        runBlocking {
            val root = Files.createTempDirectory("chat-avatar-store").toFile()
            try {
                body(root)
            } finally {
                root.deleteRecursively()
            }
        }
}
