import Foundation

public protocol SessionGateway: Sendable {
    func login(email: String, password: String) async throws -> AuthGrant
    func register(username: String, email: String, password: String, code: String) async throws -> AuthGrant
    func profile(token: String) async throws -> AuthUser
}

/// Scope each implementation to one backend. Storage errors must not fall back to plaintext.
public protocol TokenVault: Sendable {
    func read() throws -> String?
    func write(_ token: String) throws
    func clear() throws
}

public enum SessionState: Equatable, Sendable {
    case uninitialized, restoring, authenticating, clearing
    case signedOut(expired: Bool)
    case signedIn(user: AuthUser, revision: UInt64)
    case unavailable(storage: Bool, canRetryRestore: Bool)
}

public enum SessionFailure: Error, Equatable { case busy, notSignedIn, superseded, storage }
