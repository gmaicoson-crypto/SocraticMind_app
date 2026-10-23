import Foundation

/// Uses the shared transport; account validation remains authoritative on the backend.
public struct AuthAPI: SessionGateway, AccountRecoveryGateway {
    private let transport: HTTPTransport

    public init(transport: HTTPTransport) {
        self.transport = transport
    }

    public func login(email: String, password: String) async throws -> AuthGrant {
        try await decode(transport.request(method: "POST", path: "api/auth/login",
                                           form: ["username": normalizedEmail(email), "password": password]))
    }

    public func register(username: String, email: String, password: String, code: String) async throws -> AuthGrant {
        try await decode(transport.request(method: "POST", path: "api/auth/register", json: encode([
            "username": username.trimmingCharacters(in: .whitespacesAndNewlines),
            "email": normalizedEmail(email), "password": password,
            "code": code.trimmingCharacters(in: .whitespacesAndNewlines),
        ])))
    }

    public func profile(token: String) async throws -> AuthUser {
        try await decode(transport.request(method: "GET", path: "api/auth/me", bearer: token))
    }

    public func sendCode(email: String, purpose: CodePurpose) async throws -> String {
        let message: Message = try await decode(transport.request(method: "POST", path: "api/auth/send-code",
                                                                  json: encode([
                                                                      "email": normalizedEmail(email),
                                                                      "purpose": purpose.rawValue,
                                                                  ])))
        return message.message
    }

    public func resetPassword(email: String, code: String, newPassword: String) async throws -> String {
        let message: Message = try await decode(transport.request(method: "POST", path: "api/auth/reset-password",
                                                                  json: encode([
                                                                      "email": normalizedEmail(email),
                                                                      "code": code
                                                                          .trimmingCharacters(
                                                                              in: .whitespacesAndNewlines
                                                                          ),
                                                                      "new_password": newPassword,
                                                                  ])))
        return message.message
    }

    private func normalizedEmail(_ email: String) -> String {
        email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private func encode(_ fields: [String: String]) throws -> Data {
        try JSONEncoder().encode(fields)
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        try JSONDecoder().decode(T.self, from: data)
    }

    private struct Message: Decodable { let message: String }
}
