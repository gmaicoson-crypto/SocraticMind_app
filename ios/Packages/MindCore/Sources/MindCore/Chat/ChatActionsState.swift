import Foundation

public enum ChatAction: Equatable, Sendable {
    case rename(sessionID: String, title: String)
    case deleteSession(sessionID: String, title: String, discardsDraft: Bool)
    case deleteMessages(sessionID: String, ids: Set<Int64>)

    public var sessionID: String {
        switch self {
        case let .rename(id, _), let .deleteSession(id, _, _), let .deleteMessages(id, _): id
        }
    }
}

public struct ChatActionsState: Sendable {
    public internal(set) var account: HistoryAccount?
    public internal(set) var dialog: ChatAction?
    public internal(set) var busy = false
    public internal(set) var selectionSessionID: String?
    public internal(set) var selectedIDs: Set<Int64> = []
    public internal(set) var notice: String?

    public var canConfirm: Bool {
        guard !busy, let dialog else { return false }
        switch dialog {
        case let .rename(_, title):
            let clean = title.trimmingCharacters(in: .whitespacesAndNewlines)
            return !clean.isEmpty && clean.unicodeScalars.count <= 40
        case .deleteSession: return true
        case let .deleteMessages(_, ids): return (1 ... 100).contains(ids.count)
        }
    }
}

struct ChatMutationLease: Equatable, Sendable {
    let account: HistoryAccount
    let id = UUID()
}

enum ChatLibraryChange: Sendable {
    case renamed(ChatTitle), deletedSession(String), deletedMessages(String, Set<Int64>)
    var sessionID: String {
        switch self {
        case let .renamed(value): value.sessionID
        case let .deletedSession(id), let .deletedMessages(id, _): id
        }
    }
}

extension ChatLibraryState {
    mutating func apply(_ change: ChatLibraryChange) {
        switch change {
        case let .renamed(value):
            conversations.items = conversations.items.map { item in
                var result = item
                if item.sessionID == value
                    .sessionID
                {
                    result.title = value.title; result.titleStatus = value.status.rawValue
                }
                return result
            }
        default: conversations.items.removeAll { $0.sessionID == change.sessionID }
        }
        conversations.loading = nil; conversations.failure = nil
        guard let current = selected, current.sessionID == change.sessionID else { return }
        switch change {
        case let .renamed(value): selected = ChatConversation(target: current.target, title: value.title)
        case .deletedSession: selected = nil; messages = HistoryPageState()
        case let .deletedMessages(_, ids):
            messages.items.removeAll { ids.contains($0.id) }
            messages.loading = nil; messages.failure = nil
        }
    }
}
