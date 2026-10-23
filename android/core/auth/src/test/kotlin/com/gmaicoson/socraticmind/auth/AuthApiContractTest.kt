package com.gmaicoson.socraticmind.auth

import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

class AuthApiContractTest {
    private val fixture =
        Json
            .parseToJsonElement(
                Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve("auth.json")),
            ).jsonObject
    private val credentials = fixture.getValue("credentials").jsonObject

    @Test
    fun accountEndpointsMatchSharedContract() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    withTimeout(10_000) {
                        val api = AuthApi(transport)
                        val email = " " + credentials.string("email").uppercase() + " "
                        val messages = fixture.getValue("messages").jsonObject
                        for (purpose in CodePurpose.entries) {
                            assertEquals(
                                messages.string("code"),
                                api.sendCode(email, purpose),
                            )
                        }
                        val grant =
                            api.register(
                                " " + credentials.string("username") + " ",
                                email,
                                credentials.string("password"),
                                " " + credentials.string("code") + " ",
                            )
                        val expected = AuthUser.decode(fixture.getValue("user"))
                        assertEquals(expected, grant.user)
                        assertEquals(expected, api.login(email, credentials.string("password")).user)
                        assertEquals(expected, api.profile(grant.accessToken))
                        assertEquals(
                            messages.string("reset"),
                            api.resetPassword(
                                email,
                                credentials.string("code"),
                                credentials.string("new_password"),
                            ),
                        )
                        assertFalse(grant.toString().contains(grant.accessToken))
                    }
                }
            }
        }

    @Test
    fun expiredProfileIsAnExplicitUnauthorizedFailure() =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    try {
                        AuthApi(transport).profile("expired")
                        error("Expired credential must fail")
                    } catch (error: HttpFailure) {
                        assertEquals(401, error.status)
                        assertEquals("登录已失效", error.userMessage)
                    }
                }
            }
        }

    @Test
    fun invalidIdentityOrGrantDoesNotBecomeAnAccount() {
        val user = fixture.getValue("user").jsonObject
        assertThrows(IllegalArgumentException::class.java) {
            AuthUser.decode(
                JsonObject(user + ("id" to JsonPrimitive(0))),
            )
        }
        val grant = fixture.getValue("grant").jsonObject + ("user" to user)
        for ((key, value) in listOf("access_token" to "", "access_token" to "token\nheader", "token_type" to "basic")) {
            assertThrows(IllegalArgumentException::class.java) {
                AuthGrant.decode(
                    JsonObject(grant + (key to JsonPrimitive(value))),
                )
            }
        }
    }
}
