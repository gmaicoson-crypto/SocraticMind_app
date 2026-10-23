import Combine
import Foundation

/// Owns one account's finite reads. The app binds account updates before publishing them to the UI.
@MainActor
public final class ChatLibraryModel: ObservableObject {
    private enum Lane { case conversations, messages }
    private struct Read {
        let ticket: UInt64
        let task: Task<Void, Never>
    }

    @Published public private(set) var state = ChatLibraryState()
    private let session: SessionStore
    private let gateway: any ChatHistoryGateway
    private let mode: ChatMode
    private var reads: [Lane: Read] = [:]
    private var sequence: UInt64 = 0
    private var closed = false

    public init(session: SessionStore, gateway: any ChatHistoryGateway, mode: ChatMode = .normal) {
        self.session = session
        self.gateway = gateway
        self.mode = mode
    }

    public func bindAccount(_ value: SessionState) {
        let account = HistoryAccount.from(value)
        guard !closed, state.account != account else { return }
        clear()
        state.account = account
        refreshConversations()
    }

    /// Clear on logout before storage or account observation can suspend.
    public func clear() {
        reads.values.forEach { $0.task.cancel() }
        reads.removeAll()
        state = ChatLibraryState()
    }

    public func close() {
        closed = true
        clear()
    }

    public func refreshConversations() {
        readConversations(.refresh)
    }

    public func loadMoreConversations() {
        readConversations(.more)
    }

    public func refreshMessages() {
        readMessages(.refresh)
    }

    public func loadMoreMessages() {
        readMessages(.more)
    }

    public func selectConversation(_ sessionID: String) {
        guard !closed, state.account != nil, state.selected?.sessionID != sessionID,
              let summary = state.conversations.items.first(where: { $0.sessionID == sessionID }),
              let target = try? ChatTarget(sessionID: summary.sessionID, mode: mode, nodeKey: summary.nodeKey,
                                           topicID: summary.topicID ?? 0)
        else { return }
        reads.removeValue(forKey: .messages)?.task.cancel()
        state.selected = ChatConversation(target: target, title: summary.title)
        state.messages = HistoryPageState()
        refreshMessages()
    }

    public func openConversation(_ target: ChatTarget) {
        guard !closed, state.account != nil, state.selected?.target != target, target.mode == mode else { return }
        reads.removeValue(forKey: .messages)?.task.cancel()
        state.selected = ChatConversation(target: target, title: nil)
        state.messages = HistoryPageState()
        refreshMessages()
    }

    /// Invalidate earlier reads before merging authoritative IDs, so a late page cannot erase a completed turn.
    public func accept(_ receipt: ChatTurnReceipt, account: HistoryAccount) {
        guard !closed, state.account == account, receipt.pending.ownerID == account.userID else { return }
        if state.selected?.target == receipt.pending.target {
            reads.removeValue(forKey: .messages)?.task.cancel()
            let refresh = !state.messages.loaded || receipt.messages.isEmpty
            var seen: Set<Int64> = []
            state.messages.items = (receipt.messages + state.messages.items)
                .filter { seen.insert($0.id).inserted }.sorted { $0.id > $1.id }
            state.messages.loaded = true; state.messages.loading = nil; state.messages.failure = nil
            if refresh {
                refreshMessages()
            }
        }
        refreshConversations()
    }

    public func closeConversation() {
        reads.removeValue(forKey: .messages)?.task.cancel()
        state.selected = nil
        state.messages = HistoryPageState()
    }

    private func readConversations(_ operation: HistoryLoad) {
        let gateway = gateway, mode = mode
        read(.conversations, operation: operation, page: \.conversations,
             identifier: { $0.sessionID })
        { token, cursor in
            try await gateway.conversations(token: token, mode: mode, limit: 30, cursor: cursor)
        }
    }

    private func readMessages(_ operation: HistoryLoad) {
        guard let selected = state.selected?.sessionID else { return }
        let gateway = gateway
        read(.messages, operation: operation, page: \.messages, identifier: { $0.id }) { token, cursor in
            try await gateway.messages(token: token, sessionID: selected, limit: 30, cursor: cursor)
        }
    }

    private func read<Item: Sendable>(
        _ lane: Lane, operation: HistoryLoad, page: WritableKeyPath<ChatLibraryState, HistoryPageState<Item>>,
        identifier: @escaping @Sendable (Item) -> some Hashable,
        request: @escaping @Sendable (String, HistoryCursor?) async throws -> ChatHistoryPage<Item>
    ) {
        guard !closed, let account = state.account else { return }
        let current = state[keyPath: page]
        guard current.loading != operation else { return }
        if operation == .more, current.loading != nil || !current.loaded || current.nextCursor == nil {
            return
        }
        reads.removeValue(forKey: lane)?.task.cancel()
        sequence += 1
        let ticket = sequence
        let cursor = operation == .more ? current.nextCursor : nil
        state[keyPath: page].loading = operation
        state[keyPath: page].failure = nil
        let session = session
        let task = Task { [weak self] in
            let result: Result<ChatHistoryPage<Item>, Error>
            do {
                let response = try await session.authenticated { token in
                    guard await HistoryAccount.from(session.state) == account else { throw SessionFailure.superseded }
                    try Task.checkCancellation()
                    return try await request(token, cursor)
                }
                try Task.checkCancellation()
                result = .success(response)
            } catch { result = .failure(error) }
            let actualAccount = await HistoryAccount.from(session.state)
            guard let self, reads[lane]?.ticket == ticket, state.account == account else { return }
            reads.removeValue(forKey: lane)
            guard actualAccount == account else { clear(); return }
            var updated = state[keyPath: page]
            switch result {
            case let .success(response): updated.accept(response, operation: operation, identifier: identifier)
            case let .failure(error):
                updated.loading = nil
                updated.failure = historyFailure(operation, error)
            }
            state[keyPath: page] = updated
        }
        reads[lane] = Read(ticket: ticket, task: task)
    }

    deinit { reads.values.forEach { $0.task.cancel() } }
}

private func historyFailure(_ operation: HistoryLoad, _ error: Error) -> HistoryLoadFailure? {
    guard !(error is CancellationError) else { return nil }
    let message = if let failure = error as? HTTPFailure, failure.status == 404 {
        "当前服务暂不支持会话读取，请更新服务后重试。"
    } else {
        "读取失败，请检查网络与服务后重试。"
    }
    return HistoryLoadFailure(operation: operation, message: message)
}
