import Foundation

/// One actor owns credentials and state. Tokens never appear in observable snapshots.
public actor SessionStore {
    private let gateway: any SessionGateway
    private let vault: any TokenVault
    private var revision: UInt64 = 0
    private var token: String?
    public private(set) var state: SessionState = .uninitialized
    private var observers: [UUID: AsyncStream<SessionState>.Continuation] = [:]

    public init(gateway: any SessionGateway, vault: any TokenVault) {
        self.gateway = gateway
        self.vault = vault
    }

    public func updates() -> AsyncStream<SessionState> {
        let id = UUID()
        let pair = AsyncStream<SessionState>.makeStream(bufferingPolicy: .bufferingNewest(1))
        observers[id] = pair.continuation
        pair.continuation.yield(state)
        pair.continuation.onTermination = { [weak self] _ in
            Task { await self?.removeObserver(id) }
        }
        return pair.stream
    }

    public func restore() async throws {
        guard state == .uninitialized || state == .unavailable(storage: true, canRetryRestore: true)
            || state == .unavailable(storage: false, canRetryRestore: true)
        else { throw SessionFailure.busy }
        revision += 1
        let attempt = revision
        setState(.restoring)
        let saved: String?
        do { saved = try vault.read() }
        catch {
            setState(.unavailable(storage: true, canRetryRestore: true))
            if error is CancellationError {
                throw error
            }
            throw SessionFailure.storage
        }
        guard let saved else { setState(.signedOut(expired: false)); return }
        do {
            let user = try await gateway.profile(token: saved)
            try Task.checkCancellation()
            try requireCurrent(attempt)
            token = saved
            setState(.signedIn(user: user, revision: revision))
        } catch {
            if revision == attempt {
                if let failure = error as? HTTPFailure, [401, 404].contains(failure.status) {
                    try invalidate(expected: attempt, expired: true)
                } else {
                    setState(.unavailable(storage: false, canRetryRestore: true))
                }
            }
            throw error
        }
    }

    public func login(email: String, password: String) async throws {
        try await authenticate { try await self.gateway.login(email: email, password: password) }
    }

    public func register(username: String, email: String, password: String, code: String) async throws {
        try await authenticate {
            try await self.gateway.register(username: username, email: email, password: password, code: code)
        }
    }

    private func authenticate(_ request: () async throws -> AuthGrant) async throws {
        guard case .signedOut = state else { throw SessionFailure.busy }
        revision += 1
        let attempt = revision
        setState(.authenticating)
        do {
            let grant = try await request()
            try Task.checkCancellation()
            try requireCurrent(attempt)
            do {
                try vault.write(grant.accessToken)
                try Task.checkCancellation()
            } catch {
                do { try vault.clear(); setState(.signedOut(expired: false)) }
                catch { setState(.unavailable(storage: true, canRetryRestore: false)) }
                if error is CancellationError {
                    throw error
                }
                throw SessionFailure.storage
            }
            token = grant.accessToken
            setState(.signedIn(user: grant.user, revision: revision))
        } catch {
            if revision == attempt, state == .authenticating {
                setState(.signedOut(expired: false))
            }
            throw error
        }
    }

    public func authenticated<T: Sendable>(_ request: @Sendable (String) async throws -> T) async throws -> T {
        guard case .signedIn = state, let token else { throw SessionFailure.notSignedIn }
        let lease = revision
        let result: T
        do { result = try await request(token) }
        catch {
            if error is CancellationError {
                throw error
            }
            try requireCurrent(lease)
            if let failure = error as? HTTPFailure, failure.status == 401 {
                try invalidate(expected: lease, expired: true)
            }
            throw error
        }
        try Task.checkCancellation()
        try requireCurrent(lease)
        return result
    }

    public func logout() throws {
        try invalidate(expected: nil, expired: false)
    }

    private func invalidate(expected: UInt64?, expired: Bool) throws {
        if let expected, revision != expected {
            return
        }
        revision += 1
        token = nil
        setState(.clearing)
        do {
            try vault.clear()
            setState(.signedOut(expired: expired))
        } catch {
            setState(.unavailable(storage: true, canRetryRestore: false))
            throw SessionFailure.storage
        }
    }

    private func requireCurrent(_ expected: UInt64) throws {
        guard revision == expected else { throw SessionFailure.superseded }
    }

    private func setState(_ value: SessionState) {
        state = value
        for continuation in observers.values {
            continuation.yield(value)
        }
    }

    private func removeObserver(_ id: UUID) {
        observers.removeValue(forKey: id)
    }

    deinit {
        for continuation in observers.values {
            continuation.finish()
        }
    }
}
