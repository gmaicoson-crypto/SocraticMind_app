package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import com.gmaicoson.socraticmind.network.MultipartUpload
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonPrimitive
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.Base64

class ChatAvatarApiContractTest {
    private val data = avatarFixture()
    private val session = data.historyString("session_id")
    private val bytes = Base64.getDecoder().decode(data.historyString("image_base64"))

    @Test
    fun `multipart preserves Unicode and binary content then reads and deletes owned resource`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatAvatarApi(transport)
                    val result = api.upload("avatar-valid", 7, session, bytes, AvatarImageFormat.PNG)
                    val mutableBytes = bytes.copyOf()
                    val mutableFields = mutableMapOf("session_id" to session)
                    val snapshot = MultipartUpload(mutableFields, "file", "avatar.png", "image/png", mutableBytes)
                    mutableBytes.fill(0)
                    mutableFields["session_id"] = "changed"
                    assertEquals(
                        result.path,
                        transport
                            .request(
                                "POST",
                                "api/chat/avatar",
                                bearer = "avatar-valid",
                                multipart = snapshot,
                            ).historyObject()
                            .historyString("avatar_url"),
                    )
                    assertEquals(data.historyString("upload_url"), result.path)
                    assertArrayEquals(bytes, api.image(result))
                    assertArrayEquals(bytes, api.image(ChatAvatarResource.default(ChatMode.NORMAL)))
                    assertEquals(1L, api.delete("avatar-valid", session))
                    assertEquals(0L, api.delete("avatar-empty", session))
                    for (mode in ChatMode.entries) {
                        val expected =
                            data
                                .getValue("presets")
                                .historyObject()
                                .historyArray(mode.wireValue)
                                .map { (it as JsonPrimitive).content }
                        assertEquals(expected, ChatAvatarResource.presets(mode))
                    }
                }
            }
        }

    @Test
    fun `rejects external paths wrong owners wrong sessions and malformed delete counts`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatAvatarApi(transport)
                    for (token in listOf(
                        "avatar-wrong-owner",
                        "avatar-wrong-session",
                        "avatar-preset",
                        "avatar-external",
                    )) {
                        assertTrue(
                            runCatching { api.upload(token, 7, session, bytes, AvatarImageFormat.PNG) }.isFailure,
                        )
                    }
                    for (token in listOf("avatar-negative", "avatar-bool")) {
                        assertTrue(runCatching { api.delete(token, session) }.isFailure)
                    }
                    for (path in data.historyArray("invalid_paths")) {
                        assertTrue(runCatching { ChatAvatarResource((path as JsonPrimitive).content) }.isFailure)
                    }
                }
            }
        }

    @Test
    fun `upload limits and multipart header syntax fail before network use`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatAvatarApi(transport)
                    for (content in listOf(byteArrayOf(), ByteArray(5 * 1024 * 1024 + 1))) {
                        assertTrue(
                            runCatching {
                                api.upload(
                                    "avatar-valid",
                                    7,
                                    session,
                                    content,
                                    AvatarImageFormat.PNG,
                                )
                            }.isFailure,
                        )
                    }
                    for (id in listOf(" ", " x ", "🙂".repeat(101))) {
                        assertTrue(
                            runCatching { api.upload("avatar-valid", 7, id, bytes, AvatarImageFormat.PNG) }.isFailure,
                        )
                    }
                    for (name in listOf("bad\r\nheader", "\"name", "../file")) {
                        assertTrue(
                            runCatching { MultipartUpload(emptyMap(), "file", name, "image/png", bytes) }.isFailure,
                        )
                    }
                    assertTrue(
                        runCatching {
                            MultipartUpload(
                                mapOf("file" to "x"),
                                "file",
                                "a.png",
                                "image/png",
                                bytes,
                            )
                        }.isFailure,
                    )
                    assertTrue(
                        runCatching {
                            MultipartUpload(
                                emptyMap(),
                                "file",
                                "a.png",
                                "image/png\r\nx: y",
                                bytes,
                            )
                        }.isFailure,
                    )
                    val upload = MultipartUpload(emptyMap(), "file", "a.png", "image/png", bytes)
                    assertTrue(runCatching { transport.request("GET", "health", multipart = upload) }.isFailure)
                    assertTrue(
                        runCatching {
                            transport.request(
                                "POST",
                                "health",
                                form = mapOf("x" to "y"),
                                multipart = upload,
                            )
                        }.isFailure,
                    )
                }
            }
        }

    @Test
    fun `authorization rate limiting and server failures remain visible`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatAvatarApi(transport)
                    for ((token, code) in listOf("expired" to 401, "avatar-rate" to 429, "avatar-server" to 503)) {
                        val error =
                            runCatching {
                                api.upload(
                                    token,
                                    7,
                                    session,
                                    bytes,
                                    AvatarImageFormat.PNG,
                                )
                            }.exceptionOrNull()
                        assertTrue(error is HttpFailure && error.status == code)
                        val deletion = runCatching { api.delete(token, session) }.exceptionOrNull()
                        assertTrue(deletion is HttpFailure && deletion.status == code)
                    }
                }
            }
        }

    @Test
    fun `image reads reject wrong MIME empty body oversized length and redirects`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatAvatarApi(transport)
                    for (path in ChatAvatarResource.presets(ChatMode.NORMAL).subList(1, 5)) {
                        assertTrue(runCatching { api.image(ChatAvatarResource(path)) }.isFailure)
                    }
                    val redirect =
                        runCatching { api.image(ChatAvatarResource(ChatAvatarResource.presets(ChatMode.NORMAL)[3])) }
                            .exceptionOrNull()
                    assertTrue(redirect is HttpFailure && redirect.status == 302)
                    assertTrue(
                        runCatching {
                            transport.resource(
                                ChatAvatarResource.presets(ChatMode.NORMAL)[5],
                                setOf("image/png"),
                                65,
                            )
                        }.isFailure,
                    )
                }
            }
        }

    @Test
    fun `ambiguous upload is not replayed and canceled image read releases connection`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = ChatAvatarApi(transport)
                    assertTrue(
                        runCatching {
                            api.upload(
                                "avatar-disconnect",
                                7,
                                session,
                                bytes,
                                AvatarImageFormat.PNG,
                            )
                        }.isFailure,
                    )
                    assertEquals(
                        1L,
                        transport
                            .request("GET", "stats", query = mapOf("id" to "avatar-disconnect"))
                            .historyObject()
                            .historyLong("count"),
                    )
                    val job = launch { api.image(ChatAvatarResource(ChatAvatarResource.presets(ChatMode.NORMAL)[5])) }
                    withTimeout(3000) {
                        while (transport
                                .request("GET", "stats", query = mapOf("id" to "avatar-resource"))
                                .historyObject()
                                .historyLong("count") != 1L
                        ) {
                            delay(10)
                        }
                    }
                    job.cancelAndJoin()
                    withTimeout(3000) {
                        while (transport
                                .request("GET", "stats", query = mapOf("id" to "avatar-resource"))
                                .historyObject()["closed"] != JsonPrimitive(true)
                        ) {
                            delay(20)
                        }
                    }
                }
            }
        }
}
