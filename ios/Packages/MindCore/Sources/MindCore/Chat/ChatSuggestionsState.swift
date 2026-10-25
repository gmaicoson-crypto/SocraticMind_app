import CryptoKit
import Foundation

public struct ChatSuggestionContext: Equatable, Sendable {
    public let account: HistoryAccount
    public let target: ChatTarget
    public let version: String
    public let hasConversation: Bool
    public let model: String?

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.account == rhs.account && lhs.target == rhs.target && lhs.version == rhs.version &&
            lhs.hasConversation == rhs.hasConversation && lhs.model.map { Data($0.utf8) } == rhs.model
            .map { Data($0.utf8) }
    }

    public static func from(_ history: ChatLibraryState, _ turn: ChatTurnState,
                            model: String? = nil) -> ChatSuggestionContext?
    {
        guard let account = history.account, let target = history.selected?.target,
              turn.account == account, turn.target == target, history.messages.loaded else { return nil }
        let recent = Array(history.messages.items.lazy.filter {
            $0.messageType == "chat" && $0.mode == target.mode.rawValue &&
                (target.mode != .socratic || $0.topicID == target.topicID) && !$0.content
                .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
                ($0.metadata?["status"] ?? .string("complete")) == .string("complete")
        }.prefix(6))
        var digest = SHA256()
        for row in recent {
            let suffix = String(String.UnicodeScalarView(row.content.unicodeScalars.suffix(800)))
            digest.update(data: Data("\(row.id):\(row.role):\(suffix.utf8.count):\(suffix)".utf8))
        }
        let version = digest.finalize().map { String(format: "%02x", $0) }.joined()
        return ChatSuggestionContext(account: account, target: target, version: version,
                                     hasConversation: !recent.isEmpty, model: model)
    }
}

public struct ChatSuggestionChoice: Equatable, Sendable {
    public let text: String
    public let draft: String
}

public struct ChatSuggestionsState: Sendable {
    public internal(set) var context: ChatSuggestionContext?
    public internal(set) var items: [String] = []
    public internal(set) var source: SuggestionSource = .local
    public internal(set) var enabled = false
    public internal(set) var loading = false
    public internal(set) var notice: String?
    public internal(set) var choice: ChatSuggestionChoice?
}

/// Bounded memory-only LRU, owned and cleared by one account's suggestion model.
struct ChatSuggestionsCache {
    private var entries: [(ChatSuggestionContext, ChatSuggestions)] = []
    var count: Int {
        entries.count
    }

    mutating func clear() {
        entries.removeAll()
    }

    mutating func get(_ context: ChatSuggestionContext) -> ChatSuggestions? {
        guard let index = entries.firstIndex(where: { $0.0 == context }) else { return nil }
        let entry = entries.remove(at: index); entries.append(entry); return entry.1
    }

    mutating func put(_ context: ChatSuggestionContext, _ result: ChatSuggestions) {
        guard result.source == .ai, !result.items.isEmpty else { return }
        entries.removeAll { $0.0 == context }; entries.append((context, result))
        while entries.count > 30 || entries.reduce(0, { $0 + $1.1.items.reduce(0) { $0 + $1.utf8.count } }) > 65536 {
            entries.removeFirst()
        }
    }
}
