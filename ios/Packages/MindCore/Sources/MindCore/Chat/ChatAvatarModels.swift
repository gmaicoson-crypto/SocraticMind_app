import CryptoKit
import Foundation

public enum ChatAvatarFailure: Error { case invalidRequest, invalidResource, invalidRecord, conflict, capacity }

public enum AvatarImageFormat: String, CaseIterable, Sendable {
    case png, jpeg, gif, webp
    public var mimeType: String {
        "image/" + rawValue
    }
}

/// Known presets or backend-generated chat uploads, never an arbitrary external URL.
public struct ChatAvatarResource: Equatable, Hashable, Codable, Sendable {
    public let path: String
    public static let maximumImageBytes = 5 * 1024 * 1024
    public var uploaded: Bool {
        path.hasPrefix("/static/avatars/")
    }

    public init(_ path: String) throws {
        let pattern = "/static/avatars/ai_[1-9][0-9]*_[a-f0-9]{24}_[a-f0-9]{32}\\.(png|jpg|jpeg|gif|webp)"
        guard Self.presets(for: .normal).contains(path) || Self.presets(for: .socratic).contains(path) ||
            path.range(of: pattern, options: .regularExpression) == path.startIndex ..< path.endIndex
        else { throw ChatAvatarFailure.invalidResource }
        self.path = path
    }

    public func belongsTo(ownerID: Int64, sessionID: String) throws -> Bool {
        try validateHistorySession(sessionID)
        guard ownerID > 0, sessionID == sessionID.trimmingCharacters(in: .whitespacesAndNewlines)
        else { throw ChatAvatarFailure.invalidRequest }
        guard uploaded else { return true }
        let hash = SHA256.hash(data: Data(sessionID.utf8)).map { String(format: "%02x", $0) }.joined().prefix(24)
        return path.hasPrefix("/static/avatars/ai_\(ownerID)_\(hash)_")
    }

    public static func presets(for mode: ChatMode) -> [String] {
        if mode == .normal {
            return (1 ... 6).map { "/avatars/AI/normal/AI_normal\($0 == 1 ? "" : "_\($0)").webp" }
        }
        return ["female", "male"].flatMap { gender in (1 ... 3).map { "/avatars/AI/study/AI-\(gender)-\($0).webp" } }
    }

    public static func fallback(for mode: ChatMode) -> ChatAvatarResource {
        // These constants are checked against the fixed provider preset catalog by the contract tests.
        ChatAvatarResource(preset: mode == .normal ? "/avatars/AI/normal/AI_normal.webp" :
            "/avatars/AI/study/AI-male-1.webp")
    }

    private init(preset: String) {
        path = preset
    }

    public init(from decoder: any Decoder) throws {
        try self.init(decoder.singleValueContainer().decode(String.self))
    }

    public func encode(to encoder: any Encoder) throws {
        var value = encoder.singleValueContainer(); try value.encode(path)
    }
}

public protocol ChatAvatarStore: Sendable {
    func read(ownerID: Int64) async throws -> ChatAvatarChoices
    func replace(
        ownerID: Int64,
        sessionID: String,
        expected: ChatAvatarResource?,
        value: ChatAvatarResource?
    ) async throws
    func clear(ownerID: Int64) async throws
}

struct ChatAvatarChoice: Codable, Sendable {
    let sessionID: String
    let path: ChatAvatarResource
    enum CodingKeys: String, CodingKey { case sessionID = "session_id", path }
}

/// Backend identifiers are UTF-8 opaque values; Swift String dictionary keys normalize equality.
public struct ChatAvatarChoices: Sendable {
    private let values: [Data: ChatAvatarResource]
    let records: [ChatAvatarChoice]
    public var count: Int {
        values.count
    }

    public var isEmpty: Bool {
        values.isEmpty
    }

    public subscript(sessionID: String) -> ChatAvatarResource? {
        values[Data(sessionID.utf8)]
    }

    init(_ records: [ChatAvatarChoice] = []) throws {
        var values: [Data: ChatAvatarResource] = [:]
        for record in records {
            guard values.updateValue(record.path, forKey: Data(record.sessionID.utf8)) == nil
            else { throw ChatAvatarFailure.invalidRecord }
        }
        self.values = values; self.records = records
    }
}
