package com.gmaicoson.socraticmind.auth

import com.gmaicoson.socraticmind.network.HttpTransport
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.util.Locale

/** Reuses the shared transport; the backend remains authoritative for validation and account state. */
class AuthApi(
    private val transport: HttpTransport,
) : SessionGateway,
    AccountRecoveryGateway {
    override suspend fun login(
        email: String,
        password: String,
    ): AuthGrant =
        AuthGrant.decode(
            transport.request(
                "POST",
                "api/auth/login",
                form =
                    mapOf("username" to normalizedEmail(email), "password" to password),
            ),
        )

    override suspend fun register(
        username: String,
        email: String,
        password: String,
        code: String,
    ): AuthGrant =
        AuthGrant.decode(
            transport.request(
                "POST",
                "api/auth/register",
                json =
                    buildJsonObject {
                        put("username", username.trim())
                        put("email", normalizedEmail(email))
                        put("password", password)
                        put("code", code.trim())
                    },
            ),
        )

    override suspend fun profile(token: String): AuthUser =
        AuthUser.decode(transport.request("GET", "api/auth/me", bearer = token))

    override suspend fun sendCode(
        email: String,
        purpose: CodePurpose,
    ): String =
        transport
            .request(
                "POST",
                "api/auth/send-code",
                json =
                    buildJsonObject {
                        put("email", normalizedEmail(email))
                        put("purpose", purpose.wireValue)
                    },
            ).jsonObject
            .string("message")

    override suspend fun resetPassword(
        email: String,
        code: String,
        newPassword: String,
    ): String =
        transport
            .request(
                "POST",
                "api/auth/reset-password",
                json =
                    buildJsonObject {
                        put("email", normalizedEmail(email))
                        put("code", code.trim())
                        put("new_password", newPassword)
                    },
            ).jsonObject
            .string("message")

    private fun normalizedEmail(email: String) = email.trim().lowercase(Locale.ROOT)
}
