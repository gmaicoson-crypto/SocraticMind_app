import Foundation

/// Local choices only, stored separately for each account and endpoint; one app-scoped actor.
public actor FileChatAvatarStore: ChatAvatarStore {
    private struct Record: Codable {
        let schema: Int
        let ownerID: Int64
        let choices: [ChatAvatarChoice]
        enum CodingKeys: String, CodingKey { case schema, ownerID = "owner_id", choices }
    }

    private let storage: AccountFileStorage
    public init(directory: URL, endpointScope: String) throws {
        storage = try AccountFileStorage(directory: directory, endpointScope: endpointScope,
                                         namespace: "chat-avatars", maximumBytes: 512 * 1024)
    }

    public func read(ownerID: Int64) throws -> ChatAvatarChoices {
        guard let bytes = try storage.read(ownerID) else { return try ChatAvatarChoices() }
        let record = try JSONDecoder().decode(Record.self, from: bytes)
        guard record.schema == 1, record.ownerID == ownerID, record.choices.count <= 1000
        else { throw ChatAvatarFailure.invalidRecord }
        for choice in record.choices {
            guard try choice.path.belongsTo(ownerID: ownerID, sessionID: choice.sessionID)
            else { throw ChatAvatarFailure.invalidRecord }
        }
        return try ChatAvatarChoices(record.choices)
    }

    public func replace(
        ownerID: Int64,
        sessionID: String,
        expected: ChatAvatarResource?,
        value: ChatAvatarResource?
    ) throws {
        try validateHistorySession(sessionID)
        guard sessionID == sessionID.trimmingCharacters(in: .whitespacesAndNewlines),
              try value?.belongsTo(ownerID: ownerID, sessionID: sessionID) != false
        else { throw ChatAvatarFailure.invalidRequest }
        let previous = try read(ownerID: ownerID)
        guard previous[sessionID] == expected else { throw ChatAvatarFailure.conflict }
        if expected == value {
            return
        }
        var choices = previous.records.filter { !$0.sessionID.utf8.elementsEqual(sessionID.utf8) }
        if let value {
            choices.append(ChatAvatarChoice(sessionID: sessionID, path: value))
        }
        guard choices.count <= 1000 else { throw ChatAvatarFailure.capacity }
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        let bytes = try encoder.encode(Record(schema: 1, ownerID: ownerID, choices: choices))
        guard bytes.count <= 512 * 1024 else { throw ChatAvatarFailure.capacity }
        try storage.write(ownerID, bytes: bytes)
    }

    public func clear(ownerID: Int64) throws {
        try storage.remove(ownerID)
    }
}
