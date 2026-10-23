package com.gmaicoson.socraticmind.auth

import java.io.IOException

internal fun account(id: Long) = AuthUser(id, "User$id", "u$id@example.test", "", "", "", 5, "标准")

internal fun grant(id: Long) = AuthGrant("synthetic-token-$id", account(id))

internal class MemoryVault(
    initial: String? = null,
) : TokenVault {
    @Volatile var value = initial

    @Volatile var failRead = false

    @Volatile var failWriteAfterPersist = false

    @Volatile var failClear = false

    override fun read(): String? {
        if (failRead) throw IOException("vault unavailable")
        return value
    }

    override fun write(token: String) {
        value = token
        if (failWriteAfterPersist) throw IOException("write not confirmed")
    }

    override fun clear() {
        if (failClear) throw IOException("clear not confirmed")
        value = null
    }
}

internal class FakeSessionGateway : SessionGateway {
    var loginAction: suspend () -> AuthGrant = { grant(1) }
    var profileAction: suspend (String) -> AuthUser = { account(1) }
    var registrations = 0

    override suspend fun login(
        email: String,
        password: String,
    ) = loginAction()

    override suspend fun profile(token: String) = profileAction(token)

    override suspend fun register(
        username: String,
        email: String,
        password: String,
        code: String,
    ): AuthGrant {
        registrations++
        return loginAction()
    }
}
