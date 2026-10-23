import CryptoKit
import Foundation

/// App-private storage; one app-scoped actor per endpoint. Contains identifiers only, excluded from backup.
public actor FileChatTurnJournal: ChatTurnJournal {
    private struct Record: Codable {
        let schema: Int
        let pending: PendingChatTurn
    }

    private let directory: URL
    private let maximumBytes = 4096

    public init(directory: URL, endpointScope: String) throws {
        guard directory.isFileURL, !endpointScope.isEmpty else { throw ChatTurnFailure.invalidRequest }
        let hash = SHA256.hash(data: Data(endpointScope.utf8)).map { String(format: "%02x", $0) }.joined()
        self.directory = directory.appendingPathComponent("chat-turns-\(hash)", isDirectory: true)
    }

    public func read(ownerID: Int64) throws -> PendingChatTurn? {
        let file = try file(ownerID: ownerID)
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        let bytes = try handle.read(upToCount: maximumBytes + 1) ?? Data()
        guard !bytes.isEmpty, bytes.count <= maximumBytes else { throw ChatTurnFailure.journalCorrupt }
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
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var location = directory
        try location.setResourceValues(values)
        let bytes = try JSONEncoder().encode(Record(schema: 2, pending: pending))
        guard bytes.count <= maximumBytes else { throw ChatTurnFailure.journalCorrupt }
        let destination = try file(ownerID: pending.ownerID)
        #if os(iOS)
            try bytes.write(to: destination, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        #else
            try bytes.write(to: destination, options: .atomic)
        #endif
        let handle = try FileHandle(forWritingTo: destination)
        defer { try? handle.close() }
        try handle.synchronize()
        guard try read(ownerID: pending.ownerID) == pending else { throw ChatTurnFailure.journalCorrupt }
    }

    public func clear(_ pending: PendingChatTurn) throws {
        let previous = try read(ownerID: pending.ownerID)
        guard previous == nil || previous == pending else { throw ChatTurnFailure.journalConflict }
        if previous != nil {
            try FileManager.default.removeItem(at: file(ownerID: pending.ownerID))
        }
        guard try read(ownerID: pending.ownerID) == nil else { throw ChatTurnFailure.journalCorrupt }
    }

    private func file(ownerID: Int64) throws -> URL {
        guard ownerID > 0 else { throw ChatTurnFailure.invalidRequest }
        return directory.appendingPathComponent("\(ownerID).json")
    }
}
