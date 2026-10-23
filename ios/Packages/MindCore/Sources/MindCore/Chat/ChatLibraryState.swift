import Foundation

/// A new login has a new revision, even for the same user. UI state never contains credentials.
public struct HistoryAccount: Equatable, Sendable {
    public let userID: Int64
    public let revision: UInt64

    public static func from(_ state: SessionState) -> HistoryAccount? {
        guard case let .signedIn(user, revision) = state else { return nil }
        return HistoryAccount(userID: user.id, revision: revision)
    }
}

public enum HistoryLoad: Sendable { case refresh, more }

public struct HistoryLoadFailure: Equatable, Sendable {
    public let operation: HistoryLoad
    public let message: String
}

public struct HistoryPageState<Item: Sendable>: Sendable {
    public internal(set) var items: [Item] = []
    public internal(set) var nextCursor: HistoryCursor?
    public internal(set) var loaded = false
    public internal(set) var loading: HistoryLoad?
    public internal(set) var failure: HistoryLoadFailure?

    mutating func accept<ID: Hashable>(_ page: ChatHistoryPage<Item>, operation: HistoryLoad,
                                       identifier: (Item) -> ID)
    {
        let combined = operation == .refresh ? page.items : items + page.items
        var seen: Set<ID> = []
        // Deleted latest messages can move a summary into a later page; keep the newer loaded version.
        items = combined.filter { seen.insert(identifier($0)).inserted }
        nextCursor = page.nextCursor
        loaded = true
        loading = nil
        failure = nil
    }
}

public struct ChatConversation: Sendable {
    public let target: ChatTarget
    public let title: String?
    public var sessionID: String {
        target.sessionID
    }
}

public struct ChatLibraryState: Sendable {
    public internal(set) var refreshingTitles = false
    public internal(set) var titleNotice: String?
    public internal(set) var account: HistoryAccount?
    public internal(set) var conversations = HistoryPageState<ConversationSummary>()
    public internal(set) var selected: ChatConversation?
    public internal(set) var messages = HistoryPageState<StoredChatMessage>()
}
