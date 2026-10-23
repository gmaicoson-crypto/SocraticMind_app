import Foundation

public enum ChatTitleStatus: String, Decodable, Sendable { case pending, running, ready, manual, failed }

public struct ChatTitle: Decodable, Equatable, Sendable {
    public let sessionID: String
    public let title: String?
    public let status: ChatTitleStatus
    public let retryPending: Bool

    enum CodingKeys: String, CodingKey { case sessionID = "session_id", title, status, retryPending = "retry_pending" }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        sessionID = try values.decode(String.self, forKey: .sessionID)
        try validateHistorySession(sessionID)
        title = try values.decode(String?.self, forKey: .title)
        status = try values.decode(ChatTitleStatus.self, forKey: .status)
        retryPending = try values.decode(Bool.self, forKey: .retryPending)
        if let title {
            guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, title.unicodeScalars.count <= 40
            else { throw HistoryContractFailure.invalidPage }
        }
        guard title != nil || ![.ready, .manual].contains(status), !retryPending || status == .failed
        else { throw HistoryContractFailure.invalidPage }
    }
}

public protocol ChatActionsGateway: Sendable {
    func title(token: String, sessionID: String) async throws -> ChatTitle?
    func rename(token: String, sessionID: String, title: String) async throws -> ChatTitle
    func deleteSession(token: String, sessionID: String) async throws -> Int64
    func deleteMessages(token: String, ids: [Int64]) async throws -> Int64
}

/// Finite account-scoped reads and writes, using the common transport's no-replay mutation policy.
public struct ChatActionsAPI: ChatActionsGateway {
    private let transport: HTTPTransport
    public init(transport: HTTPTransport) {
        self.transport = transport
    }

    public func title(token: String, sessionID: String) async throws -> ChatTitle? {
        try validateHistorySession(sessionID)
        let data = try await transport.request(method: "GET", path: "api/chat/session-titles", bearer: token,
                                               query: ["ids": sessionID])
        let values = try JSONDecoder().decode([ChatTitle].self, from: data)
        guard values.count <= 1, values.allSatisfy({ $0.sessionID == sessionID })
        else { throw HistoryContractFailure.invalidPage }
        return values.first
    }

    public func rename(token: String, sessionID: String, title: String) async throws -> ChatTitle {
        try validateMutationSession(sessionID)
        let clean = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, clean.unicodeScalars.count <= 40 else { throw ChatTurnFailure.invalidRequest }
        let body = try JSONSerialization.data(withJSONObject: ["session_id": sessionID, "title": clean])
        let data = try await transport.request(
            method: "PUT",
            path: "api/chat/session-titles",
            bearer: token,
            json: body
        )
        let result = try JSONDecoder().decode(ChatTitle.self, from: data)
        guard result.sessionID == sessionID, result.status == .manual, result.title == clean
        else { throw HistoryContractFailure.invalidPage }
        return result
    }

    public func deleteSession(token: String, sessionID: String) async throws -> Int64 {
        try validateMutationSession(sessionID)
        return try await remove(token: token, path: "api/chat/session",
                                body: JSONSerialization.data(withJSONObject: ["session_id": sessionID]))
    }

    public func deleteMessages(token: String, ids: [Int64]) async throws -> Int64 {
        guard (1 ... 100).contains(ids.count), ids.allSatisfy({ $0 > 0 }), Set(ids).count == ids.count
        else { throw ChatTurnFailure.invalidRequest }
        let count = try await remove(token: token, path: "api/chat/messages",
                                     body: JSONSerialization.data(withJSONObject: ["ids": ids]))
        guard count <= ids.count else { throw HistoryContractFailure.invalidPage }
        return count
    }

    private func remove(token: String, path: String, body: Data) async throws -> Int64 {
        struct Result: Decodable { let deleted: Int64 }
        let data = try await transport.request(method: "DELETE", path: path, bearer: token, json: body)
        let count = try JSONDecoder().decode(Result.self, from: data).deleted
        guard count >= 0 else { throw HistoryContractFailure.invalidPage }
        return count
    }

    private func validateMutationSession(_ id: String) throws {
        try validateHistorySession(id)
        guard id == id.trimmingCharacters(in: .whitespacesAndNewlines) else { throw ChatTurnFailure.invalidRequest }
    }
}
