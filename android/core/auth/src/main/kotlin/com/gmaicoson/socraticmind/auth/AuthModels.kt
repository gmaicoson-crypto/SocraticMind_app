package com.gmaicoson.socraticmind.auth

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull

data class AuthUser(
    val id: Long,
    val username: String,
    val email: String,
    val avatarUrl: String,
    val aiAvatarUrl: String,
    val bio: String,
    val dailyGoal: Int,
    val aiStyle: String,
) {
    init {
        require(id > 0)
    }

    companion object {
        fun decode(value: JsonElement): AuthUser {
            val objectValue = value.jsonObject
            val id = objectValue.number("id").longOrNull ?: error("Invalid user id")
            val goal = objectValue.number("daily_goal").intOrNull ?: error("Invalid daily goal")
            return AuthUser(
                id,
                objectValue.string("username"),
                objectValue.string("email"),
                objectValue.string("avatar_url"),
                objectValue.string("ai_avatar_url"),
                objectValue.string("bio"),
                goal,
                objectValue.string("ai_style"),
            )
        }
    }
}

/** Credentials stay out of observable UI state and diagnostic string representations. */
class AuthGrant(
    val accessToken: String,
    val user: AuthUser,
) {
    init {
        require(accessToken.isNotBlank() && accessToken.none { it == '\r' || it == '\n' })
    }

    override fun toString() = "AuthGrant(userId=${user.id}, accessToken=<redacted>)"

    companion object {
        fun decode(value: JsonElement): AuthGrant {
            val objectValue = value.jsonObject
            val type = if ("token_type" in objectValue) objectValue.string("token_type") else "bearer"
            require(type.equals("bearer", ignoreCase = true)) { "Unsupported token type" }
            return AuthGrant(objectValue.string("access_token"), AuthUser.decode(objectValue.getValue("user")))
        }
    }
}

enum class CodePurpose(
    val wireValue: String,
) {
    REGISTER("register"),
    RESET("reset"),
}

internal fun JsonObject.string(key: String): String =
    (getValue(key) as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error("Expected string field: $key")

private fun JsonObject.number(key: String): JsonPrimitive =
    (getValue(key) as? JsonPrimitive)?.takeUnless { it.isString } ?: error("Expected number field: $key")
