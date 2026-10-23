package com.gmaicoson.socraticmind.network

import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class HttpTransportTest {
    @Test
    fun mutationsAvoidAnIdleReadOrMutationConnectionWithoutRetrying() =
        withTransport { transport ->
            transport.request("GET", "idle-seed")
            repeat(2) {
                assertEquals("ok", transport.request("POST", "fresh-mutation", json = payload()).string("status"))
            }
        }

    @Test
    fun credentialScopeIncludesSchemePortAndPrefix() {
        val base = ApiEndpoint("https://api.example.test/").credentialScope
        assertEquals(base, ApiEndpoint("HTTPS://API.EXAMPLE.TEST:443/").credentialScope)
        assertEquals(base, ApiEndpoint("https://api.example.test").credentialScope)
        for (url in listOf("https://api.example.test:444/", "https://api.example.test/mobile/")) {
            assertFalse(base == ApiEndpoint(url).credentialScope)
        }
        assertFalse(base == ApiEndpoint("http://api.example.test/", setOf("api.example.test")).credentialScope)
    }

    @Test
    fun jsonAndFormRoundTripWithoutDamagingUnicodeOrPlus() =
        withTransport { transport ->
            val reply = transport.request("POST", "echo-json", TOKEN, payload("text" to "中文🙂 + &"))
            assertEquals("中文🙂 + &", reply.string("text"))
            val form =
                transport.request(
                    "POST",
                    "echo-form",
                    form =
                        mapOf("username" to "邮箱+test@example.test", "password" to "p+& =中文"),
                )
            assertEquals("true", form.string("valid"))
            assertEquals("ok", transport.request("GET", "health").string("status"))
        }

    @Test
    fun providerStreamsPreserveTerminalState() =
        withTransport { transport ->
            for ((case, status) in listOf("complete-utf8" to "complete", "interrupted-partial" to "interrupted")) {
                val events = transport.stream("stream", TOKEN, stream(case)).toList()
                assertTrue(events.contains(ChatEvent.MessageIds(1, 2)))
                assertTrue(events.contains(ChatEvent.RequestState(status)))
                assertEquals(ChatEvent.Done, events.last())
                assertEquals(
                    if (status == "complete") "你好" else "部分",
                    events.filterIsInstance<ChatEvent.Text>().joinToString("") { it.delta },
                )
                assertEquals(status == "interrupted", events.any { it is ChatEvent.Failure })
            }
        }

    @Test
    fun firstEventArrivesBeforeTheServerFinishes() =
        withTransport { transport ->
            val events = mutableListOf<ChatEvent>()
            transport.stream("stream", TOKEN, stream("gated")).collect { event ->
                events += event
                if (event is ChatEvent.Text) {
                    transport.request(
                        "POST",
                        "release",
                        TOKEN,
                        payload("request_id" to "gated"),
                    )
                }
            }
            assertEquals(ChatEvent.Text("先到"), events.first())
            assertTrue(events.contains(ChatEvent.RequestState("complete")))
        }

    @Test
    fun abruptEofKeepsPartialTextAndNeverInventsSuccess() =
        withTransport { transport ->
            val events = mutableListOf<ChatEvent>()
            try {
                transport.stream("stream", TOKEN, stream("truncated")).collect { events += it }
                error("Truncated stream should fail")
            } catch (_: TransportFailure) {
                assertEquals(listOf(ChatEvent.Text("部分")), events)
            }
        }

    @Test
    fun cancelledCollectorClosesPendingReadWithoutReplay() =
        withTransport { transport ->
            val first = transport.stream("stream", TOKEN, stream("cancel")).take(1).toList()
            assertEquals(listOf(ChatEvent.Text("部分")), first)
            withTimeout(2_000) {
                while (true) {
                    val stats = transport.request("GET", "stats", query = mapOf("id" to "cancel"))
                    assertEquals("1", stats.string("count"))
                    if (stats.string("closed") == "true") break
                    delay(20)
                }
            }
        }

    @Test
    fun httpErrorsAndRedirectsRemainVisible() =
        withTransport { transport ->
            for ((path, token, expected) in listOf(
                Triple("fail", TOKEN, 409),
                Triple("echo-json", "expired", 401),
                Triple("redirect", TOKEN, 302),
                Triple("invalid-form", TOKEN, 422),
            )) {
                try {
                    transport.request("POST", path, token, payload("text" to "ignored"))
                    error("HTTP $expected must fail")
                } catch (error: HttpFailure) {
                    assertEquals(expected, error.status)
                    if (expected == 409) {
                        assertEquals("VERSION_CONFLICT", error.code)
                        assertEquals("版本已更新", error.userMessage)
                        assertFalse(error.retryable ?: true)
                    }
                    if (expected == 401) assertEquals("登录已失效", error.userMessage)
                    if (expected == 422) assertEquals("密码至少 8 位", error.userMessage)
                }
            }
        }

    @Test
    fun responseLimitsAndStreamMimeAreEnforced() =
        runBlocking {
            LoopbackFixture().use { fixture ->
                HttpTransport(fixture.endpoint, maximumResponseBytes = 128).use { transport ->
                    try {
                        transport.request("POST", "oversized", TOKEN, payload())
                        error("Size limit should fail")
                    } catch (_: TransportFailure) {
                        // Expected bounded read.
                    }
                    try {
                        transport.stream("stream", TOKEN, stream("wrong-type")).toList()
                        error("JSON cannot be consumed as SSE")
                    } catch (_: TransportFailure) {
                        // Expected media type check.
                    }
                }
            }
        }

    @Test
    fun endpointKeepsBasePathAndEscapesQuery() {
        val endpoint = ApiEndpoint("https://example.test/mobile/")
        val url = endpoint.url("/chat", mapOf("id" to "中文+a&b"))
        assertEquals("/mobile/chat", url.encodedPath)
        assertEquals("中文+a&b", url.queryParameter("id"))
        assertThrows(IllegalArgumentException::class.java) { ApiEndpoint("http://example.test/") }
        assertThrows(IllegalArgumentException::class.java) { ApiEndpoint("https://token@example.test/") }
        for (path in listOf("../chat", "//other.test/x", "chat?token=x", "%2e%2e/chat", "chat\\x", "")) {
            assertThrows(IllegalArgumentException::class.java) { endpoint.url(path) }
        }
    }

    private fun withTransport(block: suspend (HttpTransport) -> Unit) =
        runBlocking {
            LoopbackFixture().use { fixture ->
                HttpTransport(fixture.endpoint).use { transport -> withTimeout(10_000) { block(transport) } }
            }
        }

    private fun payload(vararg values: Pair<String, String>) =
        buildJsonObject {
            values.forEach { (key, value) -> put(key, value) }
        }

    private fun stream(case: String) = payload("case" to case, "request_id" to case)

    private fun JsonElement.string(key: String) = jsonObject.getValue(key).jsonPrimitive.content

    private companion object {
        const val TOKEN = "contract-token"
    }
}
