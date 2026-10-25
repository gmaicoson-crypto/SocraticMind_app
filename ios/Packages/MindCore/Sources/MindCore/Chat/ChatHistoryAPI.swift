import Foundation

/// Call through SessionStore.authenticated. This adapter never owns or persists credentials.
public struct ChatHistoryAPI: ChatHistoryGateway {
    private let transport: HTTPTransport

    public init(transport: HTTPTransport) {
        self.transport = transport
    }

    public func conversations(
        token: String, mode: ChatMode = .normal, limit: Int = 30, cursor: HistoryCursor? = nil
    ) async throws -> ChatHistoryPage<ConversationSummary> {
        var query = try pageQuery(limit: limit, cursor: cursor)
        query["mode"] = mode.rawValue
        let data = try await transport.request(method: "GET", path: "api/chat/sessions", bearer: token, query: query)
        let payload = try JSONDecoder().decode(HistoryPagePayload<ConversationSummary>.self, from: data)
        let page = try payload.validated(limit: limit, cursor: cursor, identifier: { $0.lastMessageID })
        guard page.items.allSatisfy({ $0.mode == mode.rawValue }),
              Set(page.items.map(\.sessionID)).count == page.items.count
        else { throw HistoryContractFailure.invalidPage }
        return page
    }

    public func messages(
        token: String, sessionID: String, limit: Int = 30, cursor: HistoryCursor? = nil
    ) async throws -> ChatHistoryPage<StoredChatMessage> {
        try validateHistorySession(sessionID)
        var query = try pageQuery(limit: limit, cursor: cursor)
        query["session_id"] = sessionID
        let data = try await transport.request(
            method: "GET",
            path: "api/chat/session-messages",
            bearer: token,
            query: query
        )
        let payload = try ChatFeedbackJSON.decode(HistoryPagePayload<StoredChatMessage>.self, from: data)
        let page = try payload.validated(limit: limit, cursor: cursor, identifier: { $0.id })
        guard page.items.allSatisfy({ $0.sessionID == sessionID }) else { throw HistoryContractFailure.invalidPage }
        return page
    }

    /// Exact lookup reuses the bounded endpoint, without confusing a neighbour with a deleted message.
    public func message(token: String, sessionID: String, id: Int64) async throws -> StoredChatMessage? {
        try validateHistorySession(sessionID)
        guard id > 0 else { throw HistoryContractFailure.invalidPage }
        let data = try await transport.request(
            method: "GET", path: "api/chat/session-messages", bearer: token,
            query: ["session_id": sessionID, "snapshot_id": String(id), "limit": "1"]
        )
        let payload = try ChatFeedbackJSON.decode(HistoryPagePayload<StoredChatMessage>.self, from: data)
        let page = try payload.validated(limit: 1, cursor: nil, identifier: { $0.id })
        guard page.snapshotID == id, page.items.allSatisfy({ $0.sessionID == sessionID }) else {
            throw HistoryContractFailure.invalidPage
        }
        return page.items.first.flatMap { $0.id == id ? $0 : nil }
    }

    private func pageQuery(limit: Int, cursor: HistoryCursor?) throws -> [String: String] {
        guard (1 ... 100).contains(limit) else { throw HistoryContractFailure.invalidPage }
        var query = ["limit": String(limit)]
        if let cursor {
            query["snapshot_id"] = String(cursor.snapshotID)
            query["before_id"] = String(cursor.beforeID)
        }
        return query
    }
}
