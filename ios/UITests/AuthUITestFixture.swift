import Foundation

struct AuthUITestCase: Decodable {
    let username: String
    let email: String
    let password: String
    let newPassword: String
}

enum AuthUITestFixture {
    static func account() async throws -> AuthUITestCase {
        let data = try await request("case/ios", method: "POST")
        return try JSONDecoder().decode(AuthUITestCase.self, from: data)
    }

    static func code(_ purpose: String) async throws -> String {
        struct Code: Decodable { let code: String }
        for _ in 0 ..< 20 {
            if let data = try? await request("code/ios/\(purpose)") {
                return try JSONDecoder().decode(Code.self, from: data).code
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw FixtureError.missingDevelopmentCode
    }

    private static func request(_ path: String, method: String = "GET") async throws -> Data {
        guard let url = URL(string: "http://127.0.0.1:8766/\(path)") else {
            throw FixtureError.invalidAddress
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 3
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw FixtureError.unavailable
        }
        return data
    }

    private enum FixtureError: Error {
        case invalidAddress, unavailable, missingDevelopmentCode
    }
}
