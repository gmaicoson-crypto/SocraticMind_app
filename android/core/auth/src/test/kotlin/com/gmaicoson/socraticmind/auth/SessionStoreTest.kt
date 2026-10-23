package com.gmaicoson.socraticmind.auth

import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.supervisorScope
import kotlinx.coroutines.withTimeout
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource
import java.io.IOException

class SessionStoreTest {
    @Test
    fun cancelledRestoreCannotExposePersistedCredential() =
        runBlocking {
            val vault = MemoryVault(grant(1).accessToken)
            val gateway =
                FakeSessionGateway().apply {
                    profileAction = {
                        currentCoroutineContext().cancel()
                        account(1)
                    }
                }
            val store = SessionStore(gateway, vault)
            val task = launch { store.restore() }
            task.join()
            assertTrue(task.isCancelled)
            assertEquals(SessionState.Unavailable(storage = false, canRetryRestore = true), store.state.value)
            assertEquals(grant(1).accessToken, vault.value)
        }

    @Test
    fun cancelledCallCannotDeliverEvenIfItsWorkerReturnsSuccess() =
        runBlocking {
            val store = signedIn()
            var delivered: String? = null
            val task =
                launch {
                    delivered =
                        store.authenticated {
                            currentCoroutineContext().cancel()
                            "private result"
                        }
                }
            task.join()
            assertTrue(task.isCancelled)
            assertNull(delivered)
            assertEquals(account(1), (store.state.value as SessionState.SignedIn).user)
        }

    @Test
    fun emptyVaultStartsSignedOutWithoutARequest() =
        runBlocking {
            val gateway = FakeSessionGateway().apply { profileAction = { error("No stored credential") } }
            val store = SessionStore(gateway, MemoryVault())
            store.restore()
            assertEquals(SessionState.SignedOut(), store.state.value)
        }

    @Test
    fun loginPersistsBeforeExposingAccountAndAuthorizedCalls() =
        runBlocking {
            val vault = MemoryVault()
            val store = SessionStore(FakeSessionGateway(), vault)
            store.restore()
            store.login("u1@example.test", "password")
            assertEquals(grant(1).accessToken, vault.value)
            assertEquals(account(1), (store.state.value as SessionState.SignedIn).user)
            assertEquals(
                "accepted",
                store.authenticated { token ->
                    assertEquals(vault.value, token)
                    "accepted"
                },
            )
            assertFalse(
                store.state.value
                    .toString()
                    .contains(grant(1).accessToken),
            )
        }

    @Test
    fun storedCredentialMustBeVerifiedBeforeUse() =
        runBlocking {
            val response = CompletableDeferred<AuthUser>()
            val started = CompletableDeferred<Unit>()
            val gateway =
                FakeSessionGateway().apply {
                    profileAction = {
                        started.complete(Unit)
                        response.await()
                    }
                }
            val store = SessionStore(gateway, MemoryVault(grant(1).accessToken))
            val restoring = async { store.restore() }
            withTimeout(2_000) { started.await() }
            assertEquals(SessionState.Restoring, store.state.value)
            assertEquals(SessionFailure.NOT_SIGNED_IN, failure { store.authenticated { it } }.reason)
            response.complete(account(1))
            restoring.await()
            assertEquals(account(1), (store.state.value as SessionState.SignedIn).user)
        }

    @Test
    fun networkFailureKeepsCredentialForExplicitRestoreRetry() =
        runBlocking {
            val vault = MemoryVault(grant(1).accessToken)
            val gateway = FakeSessionGateway().apply { profileAction = { throw IOException("offline") } }
            val store = SessionStore(gateway, vault)
            try {
                store.restore()
                error("Expected offline error")
            } catch (_: IOException) {
            }
            assertEquals(SessionState.Unavailable(storage = false, canRetryRestore = true), store.state.value)
            assertEquals(grant(1).accessToken, vault.value)
            assertEquals(SessionFailure.BUSY, failure { store.login("other", "password") }.reason)
            gateway.profileAction = { account(1) }
            store.restore()
            assertEquals(account(1), (store.state.value as SessionState.SignedIn).user)
        }

    @ParameterizedTest
    @ValueSource(ints = [401, 404])
    fun invalidOrDeletedAccountClearsStoredCredential(status: Int) =
        runBlocking {
            val vault = MemoryVault(grant(1).accessToken)
            val gateway = FakeSessionGateway().apply { profileAction = { throw http(status) } }
            val store = SessionStore(gateway, vault)
            try {
                store.restore()
                error("Expected rejected profile")
            } catch (_: HttpFailure) {
            }
            assertNull(vault.value)
            assertEquals(SessionState.SignedOut(expired = true), store.state.value)
        }

    @Test
    fun logoutDuringLoginPreventsLateCredentialCommit() =
        runBlocking {
            supervisorScope {
                val reply = CompletableDeferred<AuthGrant>()
                val started = CompletableDeferred<Unit>()
                val gateway =
                    FakeSessionGateway().apply {
                        loginAction = {
                            started.complete(Unit)
                            reply.await()
                        }
                    }
                val vault = MemoryVault()
                val store = SessionStore(gateway, vault)
                store.restore()
                val login = async { store.login("first", "password") }
                withTimeout(2_000) { started.await() }
                store.logout()
                reply.complete(grant(1))
                assertEquals(SessionFailure.SUPERSEDED, failure { login.await() }.reason)
                assertNull(vault.value)
                assertEquals(SessionState.SignedOut(), store.state.value)
            }
        }

    @Test
    fun lateSuccessFromPreviousAccountIsDiscarded() =
        runBlocking {
            supervisorScope {
                val store = signedIn()
                val reply = CompletableDeferred<String>()
                val request = async(start = CoroutineStart.UNDISPATCHED) { store.authenticated { reply.await() } }
                store.logout()
                reply.complete("private old data")
                assertEquals(SessionFailure.SUPERSEDED, failure { request.await() }.reason)
            }
        }

    @Test
    fun oldUnauthorizedResponseCannotClearNewAccount() =
        runBlocking {
            supervisorScope {
                val gateway = FakeSessionGateway()
                val vault = MemoryVault()
                val store = SessionStore(gateway, vault)
                store.restore()
                store.login("one", "password")
                val reply = CompletableDeferred<String>()
                val request = async(start = CoroutineStart.UNDISPATCHED) { store.authenticated { reply.await() } }
                store.logout()
                gateway.loginAction = { grant(2) }
                store.login("two", "password")
                reply.completeExceptionally(http(401))
                assertEquals(SessionFailure.SUPERSEDED, failure { request.await() }.reason)
                assertEquals(grant(2).accessToken, vault.value)
                assertEquals(account(2), (store.state.value as SessionState.SignedIn).user)
            }
        }

    @Test
    fun currentUnauthorizedExpiresSessionButMissingResourceDoesNot() =
        runBlocking {
            val store = signedIn()
            try {
                store.authenticated<String> { throw http(404) }
            } catch (_: HttpFailure) {
            }
            assertEquals(account(1), (store.state.value as SessionState.SignedIn).user)
            try {
                store.authenticated<String> { throw http(401) }
            } catch (_: HttpFailure) {
            }
            assertEquals(SessionState.SignedOut(expired = true), store.state.value)
        }

    @Test
    fun duplicateSubmissionDoesNotStartAnotherAuthentication() =
        runBlocking {
            val reply = CompletableDeferred<AuthGrant>()
            val started = CompletableDeferred<Unit>()
            val gateway =
                FakeSessionGateway().apply {
                    loginAction = {
                        started.complete(Unit)
                        reply.await()
                    }
                }
            val store = SessionStore(gateway, MemoryVault())
            store.restore()
            val login = async { store.login("one", "password") }
            withTimeout(2_000) { started.await() }
            assertEquals(SessionFailure.BUSY, failure { store.register("name", "two", "password", "code") }.reason)
            assertEquals(0, gateway.registrations)
            reply.complete(grant(1))
            login.await()
        }

    @Test
    fun cancelledPendingLoginReturnsToSignedOut() =
        runBlocking {
            val started = CompletableDeferred<Unit>()
            val gateway =
                FakeSessionGateway().apply {
                    loginAction = {
                        started.complete(Unit)
                        CompletableDeferred<AuthGrant>().await()
                    }
                }
            val vault = MemoryVault()
            val store = SessionStore(gateway, vault)
            store.restore()
            val login = async { store.login("one", "password") }
            withTimeout(2_000) { started.await() }
            login.cancelAndJoin()
            assertEquals(SessionState.SignedOut(), store.state.value)
            assertNull(vault.value)
        }

    @Test
    fun failedWriteRemovesEvenPartiallyPersistedCredential() =
        runBlocking {
            val vault = MemoryVault().apply { failWriteAfterPersist = true }
            val store = SessionStore(FakeSessionGateway(), vault)
            store.restore()
            assertEquals(SessionFailure.STORAGE, failure { store.login("one", "password") }.reason)
            assertNull(vault.value)
            assertEquals(SessionState.SignedOut(), store.state.value)
        }

    @Test
    fun failedClearInvalidatesMemoryAndBlocksLoginUntilCleanupSucceeds() =
        runBlocking {
            val vault = MemoryVault(grant(1).accessToken)
            val store = SessionStore(FakeSessionGateway(), vault)
            store.restore()
            vault.failClear = true
            assertEquals(SessionFailure.STORAGE, failure { store.logout() }.reason)
            assertEquals(SessionFailure.NOT_SIGNED_IN, failure { store.authenticated { it } }.reason)
            assertEquals(SessionFailure.BUSY, failure { store.login("two", "password") }.reason)
            vault.failClear = false
            store.logout()
            assertNull(vault.value)
            assertEquals(SessionState.SignedOut(), store.state.value)
        }

    @Test
    fun temporarilyUnavailableVaultCanRetryWithoutLosingCredential() =
        runBlocking {
            val vault = MemoryVault(grant(1).accessToken).apply { failRead = true }
            val store = SessionStore(FakeSessionGateway(), vault)
            assertEquals(SessionFailure.STORAGE, failure { store.restore() }.reason)
            assertEquals(SessionState.Unavailable(storage = true, canRetryRestore = true), store.state.value)
            vault.failRead = false
            store.restore()
            assertEquals(account(1), (store.state.value as SessionState.SignedIn).user)
        }

    private suspend fun signedIn(): SessionStore {
        val store = SessionStore(FakeSessionGateway(), MemoryVault())
        store.restore()
        store.login("one", "password")
        return store
    }

    private suspend fun failure(block: suspend () -> Unit): SessionException {
        try {
            block()
        } catch (error: SessionException) {
            return error
        }
        throw AssertionError("Expected SessionException")
    }

    private fun http(status: Int) = HttpFailure(status, null, "synthetic error", null)
}
