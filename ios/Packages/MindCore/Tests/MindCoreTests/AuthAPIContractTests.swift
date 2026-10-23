import Foundation
import MindCore
import Testing

struct AuthAPIContractTests {
    @Test
    func accountEndpointsMatchSharedContract() async throws {
        let fixture = try load()
        let fields = fixture.credentials
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        let api = AuthAPI(transport: transport)
        let email = " " + fields.email.uppercased() + " "
        for purpose in [CodePurpose.register, .reset] {
            #expect(try await api.sendCode(email: email, purpose: purpose) == fixture.messages.code)
        }
        let grant = try await api.register(username: " " + fields.username + " ", email: email,
                                           password: fields.password, code: " " + fields.code + " ")
        #expect(grant.user == fixture.user)
        #expect(try await api.login(email: email, password: fields.password).user == fixture.user)
        #expect(try await api.profile(token: grant.accessToken) == fixture.user)
        #expect(try await api.resetPassword(email: email, code: fields.code, newPassword: fields.new_password)
            == fixture.messages.reset)
        #expect(!grant.description.contains(grant.accessToken))
    }

    @Test
    func expiredProfileIsAnExplicitUnauthorizedFailure() async throws {
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        do {
            _ = try await AuthAPI(transport: transport).profile(token: "expired")
            Issue.record("Expired credential must fail")
        } catch let error as HTTPFailure {
            #expect(error.status == 401)
            #expect(error.userMessage == "登录已失效")
        }
    }

    @Test
    func invalidIdentityOrGrantDoesNotBecomeAnAccount() throws {
        let source = try Data(contentsOf: fixtureURL())
        let object = try #require(JSONSerialization.jsonObject(with: source) as? [String: Any])
        let user = try #require(object["user"] as? [String: Any])
        var invalidUser = user
        invalidUser["id"] = 0
        #expect(throws: (any Error).self) {
            try JSONDecoder().decode(AuthUser.self, from: JSONSerialization.data(withJSONObject: invalidUser))
        }
        var grant = try #require(object["grant"] as? [String: Any])
        grant["user"] = user
        for (key, value) in [("access_token", ""), ("access_token", "token\nheader"), ("token_type", "basic")] {
            var invalid = grant
            invalid[key] = value
            #expect(throws: (any Error).self) {
                try JSONDecoder().decode(AuthGrant.self, from: JSONSerialization.data(withJSONObject: invalid))
            }
        }
    }

    private func fixtureURL() -> URL {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        return root.appendingPathComponent("contracts/fixtures/auth.json")
    }

    private func load() throws -> Fixture {
        try JSONDecoder()
            .decode(Fixture.self, from: Data(contentsOf: fixtureURL()))
    }

    private struct Fixture: Decodable {
        let credentials: Credentials
        let user: AuthUser
        let messages: Messages
        struct Credentials: Decodable {
            let email: String; let username: String; let password: String; let code: String; let new_password: String
        }

        struct Messages: Decodable { let code: String; let reset: String }
    }
}
