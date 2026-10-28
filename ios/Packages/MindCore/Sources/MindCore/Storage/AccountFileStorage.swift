import CryptoKit
import Foundation

enum AccountFileFailure: Error { case invalidRecord }

/// Shared bounded atomic IO. The repository actor owns synchronization, schema and conflict checks.
struct AccountFileStorage: Sendable {
    private let directory: URL
    private let maximumBytes: Int

    init(directory: URL, endpointScope: String, namespace: String, maximumBytes: Int) throws {
        guard directory.isFileURL, !endpointScope.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !namespace.isEmpty, namespace.utf8.allSatisfy({ (97 ... 122).contains($0) || $0 == 45 }), maximumBytes > 0
        else { throw AccountFileFailure.invalidRecord }
        let hash = SHA256.hash(data: Data(endpointScope.utf8)).map { String(format: "%02x", $0) }.joined()
        self.directory = directory.appendingPathComponent("\(namespace)-\(hash)", isDirectory: true)
        self.maximumBytes = maximumBytes
    }

    func read(_ ownerID: Int64) throws -> Data? {
        let file = try file(ownerID)
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var bytes = Data()
        while bytes.count <= maximumBytes {
            let chunk = try handle.read(upToCount: maximumBytes + 1 - bytes.count) ?? Data()
            if chunk.isEmpty {
                break
            }
            bytes.append(chunk)
        }
        guard !bytes.isEmpty, bytes.count <= maximumBytes else { throw AccountFileFailure.invalidRecord }
        return bytes
    }

    func write(_ ownerID: Int64, bytes: Data) throws {
        guard !bytes.isEmpty, bytes.count <= maximumBytes else { throw AccountFileFailure.invalidRecord }
        let destination = try file(ownerID)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        var location = directory; try location.setResourceValues(values)
        #if os(iOS)
            try bytes.write(to: destination, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        #else
            try bytes.write(to: destination, options: .atomic)
        #endif
        let handle = try FileHandle(forWritingTo: destination)
        defer { try? handle.close() }
        try handle.synchronize()
        guard try read(ownerID) == bytes else { throw AccountFileFailure.invalidRecord }
    }

    func remove(_ ownerID: Int64) throws {
        let location = try file(ownerID)
        if FileManager.default.fileExists(atPath: location.path) {
            try FileManager.default.removeItem(at: location)
        }
        guard try read(ownerID) == nil else { throw AccountFileFailure.invalidRecord }
    }

    private func file(_ ownerID: Int64) throws -> URL {
        guard ownerID > 0 else { throw AccountFileFailure.invalidRecord }
        return directory.appendingPathComponent("\(ownerID).json")
    }
}
