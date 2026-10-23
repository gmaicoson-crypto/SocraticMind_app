package com.gmaicoson.socraticmind.auth

interface SessionGateway {
    suspend fun login(
        email: String,
        password: String,
    ): AuthGrant

    suspend fun register(
        username: String,
        email: String,
        password: String,
        code: String,
    ): AuthGrant

    suspend fun profile(token: String): AuthUser
}

/** Implementations are scoped to one backend and must never fall back to plaintext storage. */
interface TokenVault {
    fun read(): String?

    fun write(token: String)

    fun clear()
}

sealed interface SessionState {
    data object Uninitialized : SessionState

    data object Restoring : SessionState

    data object Authenticating : SessionState

    data object Clearing : SessionState

    data class SignedOut(
        val expired: Boolean = false,
    ) : SessionState

    data class SignedIn(
        val user: AuthUser,
        val revision: Long,
    ) : SessionState

    data class Unavailable(
        val storage: Boolean,
        val canRetryRestore: Boolean,
    ) : SessionState
}

enum class SessionFailure { BUSY, NOT_SIGNED_IN, SUPERSEDED, STORAGE }

class SessionException(
    val reason: SessionFailure,
) : IllegalStateException("Session ${reason.name}")
