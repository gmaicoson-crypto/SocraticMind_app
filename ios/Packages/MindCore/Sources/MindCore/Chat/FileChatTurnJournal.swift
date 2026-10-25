import Foundation

/// App-private storage; one app-scoped actor per endpoint. Contains identifiers only, excluded from backup.
public actor FileChatTurnJournal: ChatTurnJournal {
    private struct Record: Codable {
        let schema: Int
        let pending: PendingChatTurn
    }

    private let storage: AccountFileStorage

    public init(directory: URL, endpointScope: String) throws {
        guard directory.isFileURL, !endpointScope.isEmpty else { throw ChatTurnFailure.invalidRequest }
        storage = try AccountFileStorage(directory: directory, endpointScope: endpointScope,
                                         namespace: "chat-turns", maximumBytes: 4096)
    }

    public func read(ownerID: Int64) throws -> PendingChatTurn? {
        guard let bytes = try storage.read(ownerID) else { return nil }
        let record = try JSONDecoder().decode(Record.self, from: bytes)
        guard (1 ... 2).contains(record.schema), record.pending.ownerID == ownerID
        else { throw ChatTurnFailure.journalCorrupt }
        return record.pending
    }

    public func save(_ pending: PendingChatTurn) throws {
        let previous = try read(ownerID: pending.ownerID)
        guard previous == nil || previous == pending else { throw ChatTurnFailure.journalConflict }
        if previous == pending {
            return
        }
        let bytes = try JSONEncoder().encode(Record(schema: 2, pending: pending))
        try storage.write(pending.ownerID, bytes: bytes)
        guard try read(ownerID: pending.ownerID) == pending else { throw ChatTurnFailure.journalCorrupt }
    }

    public func clear(_ pending: PendingChatTurn) throws {
        let previous = try read(ownerID: pending.ownerID)
        guard previous == nil || previous == pending else { throw ChatTurnFailure.journalConflict }
        if previous != nil {
            try storage.remove(pending.ownerID)
        }
        guard try read(ownerID: pending.ownerID) == nil else { throw ChatTurnFailure.journalCorrupt }
    }
}
