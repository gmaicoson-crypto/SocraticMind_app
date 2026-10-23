import Foundation
import MindCore
import Testing

struct SessionStoreTests {
    @Test
    func cancelledRestoreCannotExposePersistedCredential() async throws {
        let grant = try sessionGrant(1)
        let vault = MemoryTokenVault(grant.accessToken)
        let gateway = FakeSessionGateway(grant)
        await gateway.setProfile {
            withUnsafeCurrentTask { $0?.cancel() }
            return grant.user
        }
        let store = SessionStore(gateway: gateway, vault: vault)
        let task = Task { try await store.restore() }
        await #expect(throws: CancellationError.self) { try await task.value }
        #expect(await store.state == .unavailable(storage: false, canRetryRestore: true))
        #expect(vault.snapshot() == grant.accessToken)
    }

    @Test
    func cancelledCallCannotDeliverEvenIfItsWorkerReturnsSuccess() async throws {
        let grant = try sessionGrant(1)
        let store = SessionStore(gateway: FakeSessionGateway(grant), vault: MemoryTokenVault())
        try await store.restore()
        try await store.login(email: "one@example.test", password: "synthetic")
        let task = Task {
            try await store.authenticated { _ in
                withUnsafeCurrentTask { $0?.cancel() }
                return "private result"
            }
        }
        await #expect(throws: CancellationError.self) { try await task.value }
        #expect(await store.state == .signedIn(user: grant.user, revision: 2))
    }

    @Test
    func emptyVaultStartsSignedOutWithoutARequest() async throws {
        let gateway = try FakeSessionGateway(sessionGrant())
        await gateway.setProfile { throw SessionTestError.offline }
        let store = SessionStore(gateway: gateway, vault: MemoryTokenVault())
        try await store.restore()
        #expect(await store.state == .signedOut(expired: false))
    }

    @Test
    func loginPersistsBeforeExposingAccountAndAuthorizedCalls() async throws {
        let grant = try sessionGrant()
        let vault = MemoryTokenVault()
        let store = SessionStore(gateway: FakeSessionGateway(grant), vault: vault)
        try await store.restore()
        try await store.login(email: "one", password: "password")
        #expect(vault.snapshot() == grant.accessToken)
        guard case let .signedIn(user, _) = await store.state else { Issue.record("Expected account"); return }
        #expect(user == grant.user)
        let result = try await store.authenticated { token in
            #expect(token == grant.accessToken)
            return "accepted"
        }
        #expect(result == "accepted")
        #expect(await !String(describing: store.state).contains(grant.accessToken))
    }

    @Test
    func storedCredentialMustBeVerifiedBeforeUse() async throws {
        let grant = try sessionGrant()
        let gateway = FakeSessionGateway(grant)
        let gate = CompletionGate<AuthUser>()
        await gateway.setProfile { try await gate.wait() }
        let store = SessionStore(gateway: gateway, vault: MemoryTokenVault(grant.accessToken))
        let task = Task { try await store.restore() }
        defer { task.cancel() }
        try await waitForGate(gate)
        #expect(await store.state == .restoring)
        await #expect(throws: SessionFailure.notSignedIn) { try await store.authenticated { $0 } }
        await gate.finish(.success(grant.user))
        try await task.value
        guard case .signedIn = await store.state else { Issue.record("Expected verified account"); return }
    }

    @Test
    func networkFailureKeepsCredentialForExplicitRestoreRetry() async throws {
        let grant = try sessionGrant()
        let vault = MemoryTokenVault(grant.accessToken)
        let gateway = FakeSessionGateway(grant)
        await gateway.setProfile { throw SessionTestError.offline }
        let store = SessionStore(gateway: gateway, vault: vault)
        await #expect(throws: SessionTestError.self) { try await store.restore() }
        #expect(await store.state == .unavailable(storage: false, canRetryRestore: true))
        #expect(vault.snapshot() == grant.accessToken)
        await #expect(throws: SessionFailure.busy) { try await store.login(email: "other", password: "password") }
        await gateway.setProfile(nil)
        try await store.restore()
        guard case .signedIn = await store.state else { Issue.record("Expected restored account"); return }
    }

    @Test(arguments: [401, 404])
    func invalidOrDeletedAccountClearsStoredCredential(status: Int) async throws {
        let grant = try sessionGrant()
        let vault = MemoryTokenVault(grant.accessToken)
        let gateway = FakeSessionGateway(grant)
        await gateway.setProfile { throw sessionHTTPFailure(status) }
        let store = SessionStore(gateway: gateway, vault: vault)
        await #expect(throws: HTTPFailure.self) { try await store.restore() }
        #expect(vault.snapshot() == nil)
        #expect(await store.state == .signedOut(expired: true))
    }

    @Test
    func logoutDuringLoginPreventsLateCredentialCommit() async throws {
        let grant = try sessionGrant()
        let gate = CompletionGate<AuthGrant>()
        let gateway = FakeSessionGateway(grant)
        await gateway.setLogin { try await gate.wait() }
        let vault = MemoryTokenVault()
        let store = SessionStore(gateway: gateway, vault: vault)
        try await store.restore()
        let task = Task { try await store.login(email: "one", password: "password") }
        defer { task.cancel() }
        try await waitForGate(gate)
        try await store.logout()
        await gate.finish(.success(grant))
        await #expect(throws: SessionFailure.superseded) { try await task.value }
        #expect(vault.snapshot() == nil)
        #expect(await store.state == .signedOut(expired: false))
    }

    @Test
    func lateSuccessFromPreviousAccountIsDiscarded() async throws {
        let store = try await signedIn()
        let gate = CompletionGate<String>()
        let task = Task { try await store.authenticated { _ in try await gate.wait() } }
        defer { task.cancel() }
        try await waitForGate(gate)
        try await store.logout()
        await gate.finish(.success("private old data"))
        await #expect(throws: SessionFailure.superseded) { try await task.value }
    }

    @Test
    func oldUnauthorizedResponseCannotClearNewAccount() async throws {
        let grant = try sessionGrant()
        let next = try sessionGrant(2)
        let vault = MemoryTokenVault()
        let gateway = FakeSessionGateway(grant)
        let store = SessionStore(gateway: gateway, vault: vault)
        try await store.restore()
        try await store.login(email: "one", password: "password")
        let gate = CompletionGate<String>()
        let task = Task { try await store.authenticated { _ in try await gate.wait() } }
        defer { task.cancel() }
        try await waitForGate(gate)
        try await store.logout()
        await gateway.setGrant(next)
        try await store.login(email: "two", password: "password")
        await gate.finish(.failure(sessionHTTPFailure(401)))
        await #expect(throws: SessionFailure.superseded) { try await task.value }
        #expect(vault.snapshot() == next.accessToken)
        guard case let .signedIn(user, _) = await store.state else { Issue.record("New account was cleared"); return }
        #expect(user == next.user)
    }

    @Test
    func currentUnauthorizedExpiresSessionButMissingResourceDoesNot() async throws {
        let store = try await signedIn()
        await #expect(throws: HTTPFailure.self) {
            try await store.authenticated { _ -> String in throw sessionHTTPFailure(404) }
        }
        guard case .signedIn = await store.state else { Issue.record("Resource 404 cleared account"); return }
        await #expect(throws: HTTPFailure.self) {
            try await store.authenticated { _ -> String in throw sessionHTTPFailure(401) }
        }
        #expect(await store.state == .signedOut(expired: true))
    }

    @Test
    func duplicateSubmissionDoesNotStartAnotherAuthentication() async throws {
        let grant = try sessionGrant()
        let gateway = FakeSessionGateway(grant)
        let gate = CompletionGate<AuthGrant>()
        await gateway.setLogin { try await gate.wait() }
        let store = SessionStore(gateway: gateway, vault: MemoryTokenVault())
        try await store.restore()
        let task = Task { try await store.login(email: "one", password: "password") }
        defer { task.cancel() }
        try await waitForGate(gate)
        await #expect(throws: SessionFailure.busy) {
            try await store.register(username: "name", email: "two", password: "password", code: "code")
        }
        #expect(await gateway.registrations == 0)
        await gate.finish(.success(grant))
        try await task.value
    }

    @Test
    func cancelledPendingLoginReturnsToSignedOut() async throws {
        let gateway = try FakeSessionGateway(sessionGrant())
        let gate = CompletionGate<AuthGrant>()
        await gateway.setLogin { try await gate.wait() }
        let vault = MemoryTokenVault()
        let store = SessionStore(gateway: gateway, vault: vault)
        try await store.restore()
        let task = Task { try await store.login(email: "one", password: "password") }
        try await waitForGate(gate)
        task.cancel()
        await #expect(throws: CancellationError.self) { try await task.value }
        #expect(await store.state == .signedOut(expired: false))
        #expect(vault.snapshot() == nil)
    }

    @Test
    func failedWriteRemovesEvenPartiallyPersistedCredential() async throws {
        let vault = MemoryTokenVault()
        vault.failWriteAfterPersist(true)
        let store = try SessionStore(gateway: FakeSessionGateway(sessionGrant()), vault: vault)
        try await store.restore()
        await #expect(throws: SessionFailure.storage) { try await store.login(email: "one", password: "password") }
        #expect(vault.snapshot() == nil)
        #expect(await store.state == .signedOut(expired: false))
    }

    @Test
    func failedClearInvalidatesMemoryAndBlocksLoginUntilCleanupSucceeds() async throws {
        let grant = try sessionGrant()
        let vault = MemoryTokenVault(grant.accessToken)
        let store = SessionStore(gateway: FakeSessionGateway(grant), vault: vault)
        try await store.restore()
        vault.failClear(true)
        await #expect(throws: SessionFailure.storage) { try await store.logout() }
        await #expect(throws: SessionFailure.notSignedIn) { try await store.authenticated { $0 } }
        await #expect(throws: SessionFailure.busy) { try await store.login(email: "two", password: "password") }
        vault.failClear(false)
        try await store.logout()
        #expect(vault.snapshot() == nil)
        #expect(await store.state == .signedOut(expired: false))
    }

    @Test
    func temporarilyUnavailableVaultCanRetryWithoutLosingCredential() async throws {
        let grant = try sessionGrant()
        let vault = MemoryTokenVault(grant.accessToken)
        vault.failRead(true)
        let store = SessionStore(gateway: FakeSessionGateway(grant), vault: vault)
        await #expect(throws: SessionFailure.storage) { try await store.restore() }
        #expect(await store.state == .unavailable(storage: true, canRetryRestore: true))
        vault.failRead(false)
        try await store.restore()
        guard case .signedIn = await store.state else { Issue.record("Expected restored account"); return }
    }

    private func signedIn() async throws -> SessionStore {
        let store = try SessionStore(gateway: FakeSessionGateway(sessionGrant()), vault: MemoryTokenVault())
        try await store.restore()
        try await store.login(email: "one", password: "password")
        return store
    }
}
