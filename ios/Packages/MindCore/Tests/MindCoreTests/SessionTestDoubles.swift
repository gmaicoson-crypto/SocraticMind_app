import Foundation
@testable import MindCore

enum SessionTestError: Error { case offline, storage, timeout }

func sessionGrant(_ id: Int64 = 1) throws -> AuthGrant {
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0 ..< 6 {
        root.deleteLastPathComponent()
    }
    let data = try Data(contentsOf: root.appendingPathComponent("contracts/fixtures/auth.json"))
    guard let fixture = try JSONSerialization.jsonObject(with: data) as? [String: Any],
          var user = fixture["user"] as? [String: Any]
    else { throw SessionTestError.storage }
    user["id"] = id
    user["username"] = "User\(id)"
    user["email"] = "u\(id)@example.test"
    let grant: [String: Any] = ["access_token": "synthetic-token-\(id)", "token_type": "bearer", "user": user]
    return try JSONDecoder().decode(AuthGrant.self, from: JSONSerialization.data(withJSONObject: grant))
}

/// Every mutable field is protected by the same lock, including test failure switches.
final class MemoryTokenVault: TokenVault, @unchecked Sendable {
    private let lock = NSLock()
    private var value: String?
    private var readFailure = false
    private var writeFailure = false
    private var clearFailure = false

    init(_ value: String? = nil) {
        self.value = value
    }

    func snapshot() -> String? {
        lock.withLock { value }
    }

    func failRead(_ enabled: Bool) {
        lock.withLock { readFailure = enabled }
    }

    func failWriteAfterPersist(_ enabled: Bool) {
        lock.withLock { writeFailure = enabled }
    }

    func failClear(_ enabled: Bool) {
        lock.withLock { clearFailure = enabled }
    }

    func read() throws -> String? {
        try lock.withLock {
            if readFailure {
                throw SessionTestError.storage
            }
            return value
        }
    }

    func write(_ token: String) throws {
        try lock.withLock {
            value = token
            if writeFailure {
                throw SessionTestError.storage
            }
        }
    }

    func clear() throws {
        try lock.withLock {
            if clearFailure {
                throw SessionTestError.storage
            }
            value = nil
        }
    }
}

actor FakeSessionGateway: SessionGateway {
    private var grant: AuthGrant
    private var loginAction: (@Sendable () async throws -> AuthGrant)?
    private var profileAction: (@Sendable () async throws -> AuthUser)?
    private(set) var registrations = 0
    init(_ grant: AuthGrant) {
        self.grant = grant
    }

    func setGrant(_ grant: AuthGrant) {
        self.grant = grant
    }

    func setLogin(_ action: @escaping @Sendable () async throws -> AuthGrant) {
        loginAction = action
    }

    func setProfile(_ action: (@Sendable () async throws -> AuthUser)?) {
        profileAction = action
    }

    func login(email _: String, password _: String) async throws -> AuthGrant {
        if let loginAction {
            return try await loginAction()
        }
        return grant
    }

    func profile(token _: String) async throws -> AuthUser {
        if let profileAction {
            return try await profileAction()
        }
        return grant.user
    }

    func register(username _: String, email: String, password: String, code _: String) async throws -> AuthGrant {
        registrations += 1
        return try await login(email: email, password: password)
    }
}

actor CompletionGate<Value: Sendable> {
    private var continuation: CheckedContinuation<Value, any Error>?
    private var result: Result<Value, any Error>?
    private(set) var waiting = false

    func wait() async throws -> Value {
        waiting = true
        return try await withTaskCancellationHandler {
            if let result {
                return try result.get()
            }
            return try await withCheckedThrowingContinuation { continuation = $0 }
        } onCancel: {
            Task { await self.finish(.failure(CancellationError())) }
        }
    }

    func finish(_ result: Result<Value, any Error>) {
        guard self.result == nil else { return }
        self.result = result
        continuation?.resume(with: result)
        continuation = nil
    }
}

func waitForGate(_ gate: CompletionGate<some Sendable>) async throws {
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while await !(gate.waiting) {
        guard ContinuousClock.now < deadline else { throw SessionTestError.timeout }
        try await Task.sleep(for: .milliseconds(1))
    }
}

func sessionHTTPFailure(_ status: Int) -> HTTPFailure {
    HTTPFailure(status: status, code: nil, userMessage: "synthetic error", retryable: nil)
}
