import Foundation

public enum ChatKind: String, Sendable { case qa, topicOverview = "topic_overview", nodeOverview = "node_overview" }

/// In-memory request values; recovery continues to persist identifiers without quoted content.
public struct ChatRequestContext: Sendable {
    public let kind: ChatKind
    public let quoteText: String?
    public let quoteSourceID: Int64?
    public let attachmentIDs: [String]
    public static let plain = ChatRequestContext()

    private init() {
        kind = .qa; quoteText = nil; quoteSourceID = nil; attachmentIDs = []
    }

    public init(kind: ChatKind = .qa, quoteText: String? = nil, quoteSourceID: Int64? = nil,
                attachmentIDs: [String] = []) throws
    {
        guard (quoteText?.unicodeScalars.count ?? 0) <= 200,
              quoteSourceID == nil || ((quoteSourceID ?? 0) > 0 && !(quoteText ?? "").isEmpty),
              attachmentIDs.count <= 9,
              Set(attachmentIDs.map { Data($0.utf8) }).count == attachmentIDs.count,
              attachmentIDs.allSatisfy({ !$0.isEmpty && $0.unicodeScalars.count <= 36 }),
              kind == .qa || attachmentIDs.isEmpty
        else { throw ChatTurnFailure.invalidRequest }
        self.kind = kind; self.quoteText = quoteText; self.quoteSourceID = quoteSourceID
        self.attachmentIDs = attachmentIDs
    }

    func validate(input: String, target: ChatTarget) throws {
        guard input.unicodeScalars.count <= 5000,
              !input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || kind != .qa || !attachmentIDs.isEmpty,
              kind == .qa || (target.mode == .socratic && target.topicID > 0)
        else { throw ChatTurnFailure.invalidRequest }
    }
}
