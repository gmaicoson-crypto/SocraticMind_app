package com.gmaicoson.socraticmind.auth

import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** One owner per backend. Network calls never hold the storage/state lock. */
class SessionStore(
    private val gateway: SessionGateway,
    private val vault: TokenVault,
    private val storageDispatcher: CoroutineDispatcher = Dispatchers.IO,
) {
    private val mutex = Mutex()
    private val mutableState = MutableStateFlow<SessionState>(SessionState.Uninitialized)
    val state: StateFlow<SessionState> = mutableState.asStateFlow()
    private var revision = 0L
    private var token: String? = null

    suspend fun restore() {
        val attempt =
            mutex.withLock {
                val current = mutableState.value
                if (current != SessionState.Uninitialized &&
                    !(current is SessionState.Unavailable && current.canRetryRestore)
                ) {
                    throw SessionException(SessionFailure.BUSY)
                }
                revision++
                mutableState.value = SessionState.Restoring
                val saved =
                    try {
                        withContext(storageDispatcher) { vault.read() }
                    } catch (error: Exception) {
                        mutableState.value = SessionState.Unavailable(storage = true, canRetryRestore = true)
                        if (error is CancellationException) throw error
                        throw SessionException(SessionFailure.STORAGE)
                    }
                if (saved == null) {
                    mutableState.value = SessionState.SignedOut()
                    return
                }
                revision to saved
            }
        try {
            val user = gateway.profile(attempt.second)
            currentCoroutineContext().ensureActive()
            mutex.withLock {
                requireCurrent(attempt.first)
                token = attempt.second
                mutableState.value = SessionState.SignedIn(user, revision)
            }
        } catch (error: Exception) {
            if (error is HttpFailure && error.status in setOf(401, 404)) {
                invalidate(attempt.first, expired = true)
            } else {
                withContext(NonCancellable) {
                    mutex.withLock {
                        if (revision == attempt.first) {
                            mutableState.value = SessionState.Unavailable(storage = false, canRetryRestore = true)
                        }
                    }
                }
            }
            throw error
        }
    }

    suspend fun login(
        email: String,
        password: String,
    ) = authenticate { gateway.login(email, password) }

    suspend fun register(
        username: String,
        email: String,
        password: String,
        code: String,
    ) = authenticate { gateway.register(username, email, password, code) }

    private suspend fun authenticate(request: suspend () -> AuthGrant) {
        val attempt =
            mutex.withLock {
                if (mutableState.value !is SessionState.SignedOut) throw SessionException(SessionFailure.BUSY)
                revision++
                mutableState.value = SessionState.Authenticating
                revision
            }
        try {
            val grant = request()
            currentCoroutineContext().ensureActive()
            mutex.withLock {
                requireCurrent(attempt)
                try {
                    withContext(storageDispatcher) { vault.write(grant.accessToken) }
                } catch (error: Exception) {
                    withContext(NonCancellable + storageDispatcher) {
                        try {
                            vault.clear()
                            mutableState.value = SessionState.SignedOut()
                        } catch (_: Exception) {
                            mutableState.value = SessionState.Unavailable(storage = true, canRetryRestore = false)
                        }
                    }
                    if (error is CancellationException) throw error
                    throw SessionException(SessionFailure.STORAGE)
                }
                token = grant.accessToken
                mutableState.value = SessionState.SignedIn(grant.user, revision)
            }
        } catch (error: Exception) {
            withContext(NonCancellable) {
                mutex.withLock {
                    if (revision == attempt && mutableState.value == SessionState.Authenticating) {
                        mutableState.value = SessionState.SignedOut()
                    }
                }
            }
            throw error
        }
    }

    /** A late success or 401 from an older account cannot update the current account. */
    suspend fun <T> authenticated(request: suspend (String) -> T): T {
        val lease =
            mutex.withLock {
                if (mutableState.value !is SessionState.SignedIn) throw SessionException(SessionFailure.NOT_SIGNED_IN)
                revision to checkNotNull(token)
            }
        val result =
            try {
                request(lease.second)
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                if (error is HttpFailure && error.status == 401) {
                    invalidate(lease.first, expired = true)
                } else {
                    mutex.withLock { requireCurrent(lease.first) }
                }
                throw error
            }
        currentCoroutineContext().ensureActive()
        mutex.withLock { requireCurrent(lease.first) }
        return result
    }

    suspend fun logout() = invalidate(expectedRevision = null, expired = false)

    private suspend fun invalidate(
        expectedRevision: Long?,
        expired: Boolean,
    ) {
        withContext(NonCancellable) {
            mutex.withLock {
                if (expectedRevision != null) requireCurrent(expectedRevision)
                revision++
                token = null
                mutableState.value = SessionState.Clearing
                try {
                    withContext(storageDispatcher) { vault.clear() }
                    mutableState.value = SessionState.SignedOut(expired)
                } catch (_: Exception) {
                    mutableState.value = SessionState.Unavailable(storage = true, canRetryRestore = false)
                    throw SessionException(SessionFailure.STORAGE)
                }
            }
        }
    }

    private fun requireCurrent(expected: Long) {
        if (revision != expected) throw SessionException(SessionFailure.SUPERSEDED)
    }
}
