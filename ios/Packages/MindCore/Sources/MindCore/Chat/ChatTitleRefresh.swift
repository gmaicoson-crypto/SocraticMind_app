import Foundation

/// A read-only capability; the backend continues to own title generation and its retries.
public protocol ChatTitlesGateway: Sendable {
    func titles(token: String, sessionIDs: [String]) async throws -> [ChatTitle]
}

extension ChatLibraryState {
    func titleCandidates(newerPageFirst: Bool) -> [String] {
        let items = newerPageFirst ? Array(conversations.items.reversed()) : conversations.items
        let candidates = items.filter { !["ready", "manual"].contains($0.titleStatus ?? "") }
        var ids = candidates.map(\.sessionID)
        if let opened = selected?.sessionID,
           ids.contains(opened) || !items.contains(where: { $0.sessionID == opened })
        {
            ids.removeAll { $0 == opened }; ids.insert(opened, at: 0)
        }
        return Array(ids.prefix(100))
    }

    mutating func applyTitles(_ titles: [ChatTitle]) {
        let byID = Dictionary(uniqueKeysWithValues: titles.map { ($0.sessionID, $0) })
        conversations.items = conversations.items.map { row in
            guard let title = byID[row.sessionID] else { return row }
            var updated = row; updated.title = title.title; updated.titleStatus = title.status.rawValue
            return updated
        }
        if let current = selected, let title = byID[current.sessionID] {
            selected = ChatConversation(target: current.target, title: title.title)
        }
    }
}

extension ChatTitle {
    var awaitingGeneration: Bool {
        status == .pending || status == .running || (status == .failed && retryPending)
    }
}
