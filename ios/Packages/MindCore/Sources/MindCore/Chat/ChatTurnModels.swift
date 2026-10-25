import Foundation

public enum ChatTurnFailure: Error { case invalidRequest, invalidResponse, journalConflict, journalCorrupt }

/// A new conversation has a target, without inventing a stored message ID.
public struct ChatTarget: Equatable, Codable, Sendable {
    public let sessionID: String
    public let mode: ChatMode
    public let nodeKey: String
    public let topicID: Int64

    enum CodingKeys: String,
        CodingKey { case sessionID = "session_id", mode, nodeKey = "node_key", topicID = "topic_id" }

    public init(sessionID: String, mode: ChatMode = .normal, nodeKey: String = "__normal__",
                topicID: Int64 = 0) throws
    {
        try validateHistorySession(sessionID)
        guard sessionID == sessionID.trimmingCharacters(in: .whitespacesAndNewlines),
              nodeKey == nodeKey.trimmingCharacters(in: .whitespacesAndNewlines),
              !nodeKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              nodeKey.unicodeScalars.count <= 200, topicID >= 0
        else { throw ChatTurnFailure.invalidRequest }
        self.sessionID = sessionID; self.mode = mode; self.nodeKey = nodeKey; self.topicID = topicID
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(sessionID: values.decode(String.self, forKey: .sessionID),
                      mode: values.decode(ChatMode.self, forKey: .mode),
                      nodeKey: values.decode(String.self, forKey: .nodeKey),
                      topicID: values.decode(Int64.self, forKey: .topicID))
    }
}

/// Only identifiers are persisted; no prompt, token or model credentials.
public struct PendingChatTurn: Equatable, Codable, Sendable {
    public let ownerID: Int64
    public let target: ChatTarget
    public let requestID: String
    public let regenerateMessageID: Int64?

    enum CodingKeys: String, CodingKey {
        case ownerID = "owner_id", target, requestID = "request_id", regenerateMessageID = "regenerate_message_id"
    }

    public init(ownerID: Int64, target: ChatTarget, requestID: String, regenerateMessageID: Int64? = nil) throws {
        let allowed = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-".utf8)
        guard ownerID > 0, (1 ... 100).contains(requestID.utf8.count),
              requestID.utf8.allSatisfy({ allowed.contains($0) }),
              regenerateMessageID == nil || (regenerateMessageID ?? 0) > 0
        else { throw ChatTurnFailure.invalidRequest }
        self.ownerID = ownerID; self.target = target; self.requestID = requestID
        self.regenerateMessageID = regenerateMessageID
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(ownerID: values.decode(Int64.self, forKey: .ownerID),
                      target: values.decode(ChatTarget.self, forKey: .target),
                      requestID: values.decode(String.self, forKey: .requestID),
                      regenerateMessageID: values.decodeIfPresent(Int64.self, forKey: .regenerateMessageID))
    }
}

public struct ChatTurnRequest: Sendable {
    public let pending: PendingChatTurn
    public let input: String
    public let style: String
    public let context: ChatRequestContext
    public let model: String?

    public init(
        pending: PendingChatTurn,
        input: String,
        style: String,
        context: ChatRequestContext = .plain,
        model: String? = nil
    ) throws {
        try context.validate(input: input, target: pending.target)
        try validateModelID(model)
        guard !style.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, style.unicodeScalars.count <= 20
        else { throw ChatTurnFailure.invalidRequest }
        self.pending = pending; self.input = input; self.style = style; self.context = context; self.model = model
    }

    public func encoded() throws -> Data {
        var value: [String: Any] = [
            "request_id": pending.requestID, "session_id": pending.target.sessionID,
            "node_key": pending.target.nodeKey, "topic_id": pending.target.topicID,
            "mode": pending.target.mode.rawValue, "kind": context.kind.rawValue, "user_input": input, "ai_style": style,
        ]
        if let model {
            value["model"] = model
        }
        if let id = pending.regenerateMessageID {
            value["regenerate_message_id"] = id
        }
        if let quote = context.quoteText {
            value["quote_text"] = quote
        }
        if let source = context.quoteSourceID {
            value["quote_source_id"] = source
        }
        if !context.attachmentIDs.isEmpty {
            value["attachment_ids"] = context.attachmentIDs
        }
        return try JSONSerialization.data(withJSONObject: value)
    }
}

public enum ChatTurnStatus: String, Decodable, Sendable {
    case generating, complete, failed, interrupted
    public var terminal: Bool {
        self != .generating
    }
}

public struct ChatMessageIDs: Equatable, Decodable, Sendable {
    public let user: Int64
    public let ai: Int64

    public init(user: Int64, ai: Int64) throws {
        guard user > 0, ai > 0, user != ai else { throw ChatTurnFailure.invalidResponse }
        self.user = user; self.ai = ai
    }

    enum CodingKeys: String, CodingKey { case user, ai }
    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(user: values.decode(Int64.self, forKey: .user), ai: values.decode(Int64.self, forKey: .ai))
    }
}

public struct RemoteChatTurn: Sendable {
    public let status: ChatTurnStatus
    public let ids: ChatMessageIDs?
    public init(status: ChatTurnStatus, ids: ChatMessageIDs?) {
        self.status = status; self.ids = ids
    }
}

public protocol ChatTurnGateway: Sendable {
    func stream(token: String, request: ChatTurnRequest,
                onEvent: @Sendable (ChatEvent) async throws -> Void) async throws
    func status(token: String, pending: PendingChatTurn) async throws -> RemoteChatTurn
    func cancel(token: String, pending: PendingChatTurn) async throws -> RemoteChatTurn
    func messages(token: String, pending: PendingChatTurn, ids: ChatMessageIDs) async throws -> [StoredChatMessage]
}

public protocol ChatTurnJournal: Sendable {
    func read(ownerID: Int64) async throws -> PendingChatTurn?
    /// Save durably before POST; never overwrite a different unconfirmed request.
    func save(_ pending: PendingChatTurn) async throws
    /// Compare request IDs before removal to protect a newer attempt from stale cleanup.
    func clear(_ pending: PendingChatTurn) async throws
}
