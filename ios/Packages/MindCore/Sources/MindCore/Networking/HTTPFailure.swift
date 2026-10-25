import Foundation

public enum TransportFailure: Error, Equatable {
    case invalidEndpoint, invalidPath, invalidRequest, invalidResponse
    case expectedJSON, expectedSSE, responseTooLarge, incompleteStream, unexpectedResourceType
}

public struct HTTPFailure: Error, Sendable {
    public let status: Int
    public let code: String?
    public let userMessage: String
    public let retryable: Bool?

    static func decode(status: Int, data: Data) -> HTTPFailure {
        let payload = try? JSONDecoder().decode(Payload.self, from: data)
        return HTTPFailure(
            status: status,
            code: payload?.code,
            userMessage: payload?.message ?? payload?.detail?.message ?? "请求失败（HTTP \(status)）",
            retryable: payload?.retryable
        )
    }

    private struct Payload: Decodable {
        let code: String?
        let message: String?
        let retryable: Bool?
        let detail: Detail?
    }

    private struct Detail: Decodable {
        let message: String?
        init(from decoder: any Decoder) throws {
            let value = try decoder.singleValueContainer()
            if let text = try? value.decode(String.self) {
                message = text; return
            }
            let issues = try value.decode([Issue].self)
            let text = issues.first?.msg
            message = text.map { $0.hasPrefix("Value error, ") ? String($0.dropFirst(13)) : $0 }
        }

        private struct Issue: Decodable { let msg: String }
    }
}
