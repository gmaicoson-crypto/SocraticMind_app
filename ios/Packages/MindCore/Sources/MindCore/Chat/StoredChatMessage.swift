import Foundation

/// Keep structured learning, sources and attachments for their feature consumers, including unknown additions.
public struct StoredChatMessage: Decodable, Equatable, Sendable {
    public let id: Int64
    public let role: String
    public let content: String
    public let nodeKey: String
    public let mode: String
    public let topicID: Int64?
    public let sessionID: String
    public let messageType: String
    public let metadata: [String: ChatJSONValue]?
    public let createdAt: String?
    public let attachments: [[String: ChatJSONValue]]

    enum CodingKeys: String, CodingKey {
        case id, role, content, nodeKey = "node_key", mode, topicID = "topic_id", sessionID = "session_id"
        case messageType = "message_type", metadata, createdAt = "created_at", attachments
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(Int64.self, forKey: .id)
        guard id > 0 else { throw HistoryContractFailure.invalidPage }
        sessionID = try values.decode(String.self, forKey: .sessionID)
        try validateHistorySession(sessionID)
        role = try values.decode(String.self, forKey: .role)
        content = try values.decode(String.self, forKey: .content)
        nodeKey = try values.decode(String.self, forKey: .nodeKey)
        mode = try values.decode(String.self, forKey: .mode)
        topicID = try values.decode(Int64?.self, forKey: .topicID)
        messageType = try values.decode(String.self, forKey: .messageType)
        metadata = try values.decode([String: ChatJSONValue]?.self, forKey: .metadata)
        createdAt = try values.decode(String?.self, forKey: .createdAt)
        attachments = try values.decode([[String: ChatJSONValue]].self, forKey: .attachments)
    }
}

/// Int64 remains exact for resource IDs; do not round every JSON number through Double.
public enum ChatJSONValue: Decodable, Equatable, Sendable {
    case null, bool(Bool), integer(Int64), decimal(Double), string(String)
    case array([ChatJSONValue]), object([String: ChatJSONValue])

    public init(from decoder: any Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() {
            self = .null
        } else if let result = try? value.decode(Bool.self) {
            self = .bool(result)
        } else if let result = try? value.decode(Int64.self) {
            self = .integer(result)
        } else if let result = try? value.decode(Double.self) {
            self = .decimal(result)
        } else if let result = try? value.decode(String.self) {
            self = .string(result)
        } else if let result = try? value.decode([ChatJSONValue].self) {
            self = .array(result)
        } else {
            self = try .object(value.decode([String: ChatJSONValue].self))
        }
    }
}
