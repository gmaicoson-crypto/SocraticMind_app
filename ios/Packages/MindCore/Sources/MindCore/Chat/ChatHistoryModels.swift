import Foundation

public enum ChatMode: String, Sendable { case normal, socratic }

public enum HistoryContractFailure: Error { case invalidCursor, invalidPage, invalidSession }

/// Carry the original upper bound to older pages; a refresh starts without a cursor.
public struct HistoryCursor: Equatable, Sendable {
    public let snapshotID: Int64
    public let beforeID: Int64

    public init(snapshotID: Int64, beforeID: Int64) throws {
        guard snapshotID > 0, beforeID > 0, beforeID <= snapshotID else {
            throw HistoryContractFailure.invalidCursor
        }
        self.snapshotID = snapshotID
        self.beforeID = beforeID
    }
}

public struct ChatHistoryPage<Item: Sendable>: Sendable {
    public let items: [Item]
    public let snapshotID: Int64
    public let nextCursor: HistoryCursor?
}

extension ChatHistoryPage: Equatable where Item: Equatable {}

public struct ConversationSummary: Decodable, Equatable, Sendable {
    public let sessionID: String
    public let mode: String
    public let topicID: Int64?
    public let nodeKey: String
    public let lastMessageID: Int64
    public let lastRole: String
    public let preview: String
    public let updatedAt: String?
    public let title: String?
    public let titleStatus: String?

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id", mode, topicID = "topic_id", nodeKey = "node_key"
        case lastMessageID = "last_message_id", lastRole = "last_role", preview
        case updatedAt = "updated_at", title, titleStatus = "title_status"
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        sessionID = try values.decode(String.self, forKey: .sessionID)
        try validateHistorySession(sessionID)
        mode = try values.decode(String.self, forKey: .mode)
        topicID = try values.decode(Int64?.self, forKey: .topicID)
        nodeKey = try values.decode(String.self, forKey: .nodeKey)
        lastMessageID = try values.decode(Int64.self, forKey: .lastMessageID)
        guard lastMessageID > 0 else { throw HistoryContractFailure.invalidPage }
        lastRole = try values.decode(String.self, forKey: .lastRole)
        preview = try values.decode(String.self, forKey: .preview)
        updatedAt = try values.decode(String?.self, forKey: .updatedAt)
        title = try values.decode(String?.self, forKey: .title)
        titleStatus = try values.decode(String?.self, forKey: .titleStatus)
    }
}

func validateHistorySession(_ value: String) throws {
    guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, value.unicodeScalars.count <= 100 else {
        throw HistoryContractFailure.invalidSession
    }
}

struct HistoryPagePayload<Item: Decodable & Sendable>: Decodable {
    let items: [Item]
    let snapshotID: Int64
    let nextBeforeID: Int64?

    enum CodingKeys: String, CodingKey {
        case items, snapshotID = "snapshot_id", nextBeforeID = "next_before_id"
    }

    init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        items = try values.decode([Item].self, forKey: .items)
        snapshotID = try values.decode(Int64.self, forKey: .snapshotID)
        nextBeforeID = try values.decode(Int64?.self, forKey: .nextBeforeID)
    }

    func validated(limit: Int, cursor: HistoryCursor?, identifier: (Item) -> Int64) throws -> ChatHistoryPage<Item> {
        let ids = items.map(identifier)
        guard snapshotID >= 0, items.count <= limit,
              ids.allSatisfy({ $0 > 0 && $0 <= snapshotID }),
              zip(ids, ids.dropFirst()).allSatisfy({ $0.0 > $0.1 }),
              nextBeforeID == nil || (!ids.isEmpty && nextBeforeID == ids.last)
        else { throw HistoryContractFailure.invalidPage }
        if let cursor {
            guard snapshotID == cursor.snapshotID, ids.allSatisfy({ $0 < cursor.beforeID }) else {
                throw HistoryContractFailure.invalidPage
            }
        }
        return try ChatHistoryPage(items: items, snapshotID: snapshotID,
                                   nextCursor: nextBeforeID
                                       .map { try HistoryCursor(snapshotID: snapshotID, beforeID: $0) })
    }
}
