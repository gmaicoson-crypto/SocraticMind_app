import Combine
import Foundation

/// Finite user-confirmed mutations. The existing library and turn models retain their state ownership.
@MainActor
public final class ChatActionsModel: ObservableObject {
    @Published public private(set) var state = ChatActionsState()
    private let session: SessionStore
    private let gateway: any ChatActionsGateway
    private let library: ChatLibraryModel
    private let turn: ChatTurnModel
    private let onSessionDeleted: @MainActor (HistoryAccount, String) async -> String?
    private var task: Task<Void, Never>?
    private var lease: ChatMutationLease?
    private var sequence: UInt64 = 0
    private var closed = false

    public init(session: SessionStore, gateway: any ChatActionsGateway, library: ChatLibraryModel,
                turn: ChatTurnModel,
                onSessionDeleted: @escaping @MainActor (HistoryAccount, String) async -> String? = { _, _ in nil })
    {
        self.session = session; self.gateway = gateway; self.library = library; self.turn = turn
        self.onSessionDeleted = onSessionDeleted
    }

    public func bindAccount(_ value: SessionState) {
        let account = HistoryAccount.from(value)
        guard !closed, state.account != account else { return }
        clear(); state.account = account
    }

    public func clear() {
        sequence += 1; task?.cancel(); task = nil
        if let lease {
            turn.releaseHistoryMutation(lease)
        }
        lease = nil; state = ChatActionsState()
    }

    public func close() {
        closed = true; clear()
    }

    public func canManage(_ sessionID: String) -> Bool {
        current && !state.busy && turn.state.editable && knownSession(sessionID)
    }

    public func rename(_ sessionID: String) {
        guard canManage(sessionID) else { return }
        state.dialog = .rename(sessionID: sessionID, title: title(sessionID)); state.notice = nil
    }

    public func deleteSession(_ sessionID: String) {
        guard canManage(sessionID) else { return }
        state.dialog = .deleteSession(sessionID: sessionID, title: title(sessionID),
                                      discardsDraft: turn.state.target?.sessionID == sessionID && !turn.state.draft
                                          .isEmpty)
        state.notice = nil
    }

    public func editTitle(_ value: String) {
        guard current, !state.busy, case let .rename(id, _) = state.dialog else { return }
        state.dialog = .rename(sessionID: id, title: value); state.notice = nil
    }

    public func selectMessages() {
        guard let selected = library.state.selected?.sessionID, canManage(selected) else { return }
        state.selectionSessionID = selected; state.selectedIDs = []; state.dialog = nil; state.notice = nil
    }

    public func toggleMessage(_ id: Int64) {
        guard current, !state.busy, turn.state.editable, let selected = state.selectionSessionID,
              selected == library.state.selected?.sessionID,
              library.state.messages.items.contains(where: { $0.id == id }) else { return }
        if !state.selectedIDs.contains(id), state.selectedIDs.count >= 100 {
            state.notice = "一次最多选择 100 条消息。"; return
        }
        if state.selectedIDs.contains(id) {
            state.selectedIDs.remove(id)
        } else {
            state.selectedIDs.insert(id)
        }
        state.notice = nil
    }

    public func deleteSelectedMessages() {
        guard let selected = state.selectionSessionID, canManage(selected),
              selected == library.state.selected?.sessionID else { return }
        let available = Set(library.state.messages.items.map(\.id))
        let ids = state.selectedIDs.intersection(available)
        state.selectedIDs = ids
        state.dialog = ids.isEmpty ? nil : .deleteMessages(sessionID: selected, ids: ids)
        state.notice = nil
    }

    public func cancelDialog() {
        guard !state.busy else { return }
        state.dialog = nil; state.notice = nil
    }

    public func dismiss() {
        guard !state.busy else { return }
        state = ChatActionsState(account: state.account)
    }

    public func confirm() {
        guard current, state.canConfirm, let action = state.dialog, let account = state.account else { return }
        guard valid(action) else { state.notice = "会话内容已变化，请刷新后重新选择。"; return }
        guard let reservation = turn.reserveHistoryMutation(account) else {
            state.notice = "请先等待或处理当前回答，再修改会话。"; return
        }
        lease = reservation; sequence += 1
        let ticket = sequence, session = session, gateway = gateway
        state.busy = true; state.notice = nil
        task = Task { [weak self] in
            let result: Result<ChatLibraryChange, Error>
            var cleanupNotice: String?
            do {
                let change = try await session.authenticated { token in
                    guard await HistoryAccount.from(session.state) == account else { throw SessionFailure.superseded }
                    try Task.checkCancellation()
                    return try await Self.perform(gateway, token: token, action: action)
                }
                try Task.checkCancellation()
                if case let .deletedSession(id) = change {
                    cleanupNotice = await self?.onSessionDeleted(account, id)
                }
                result = .success(change)
            } catch { result = .failure(error) }
            let actualAccount = await HistoryAccount.from(session.state)
            guard let self, sequence == ticket else { return }
            guard current, actualAccount == account else { clear(); return }
            task = nil
            switch result {
            case let .success(change):
                library.accept(change, account: account)
                let deleted: String? = if case let .deletedSession(id) = change {
                    id
                } else {
                    nil
                }
                turn.releaseHistoryMutation(reservation, deletedSessionID: deleted)
                state = ChatActionsState(account: account, notice: cleanupNotice)
            case let .failure(error):
                turn.releaseHistoryMutation(reservation)
                state.busy = false; state.notice = actionFailure(error)
            }
            lease = nil
        }
    }

    private nonisolated static func perform(_ gateway: any ChatActionsGateway, token: String,
                                            action: ChatAction) async throws -> ChatLibraryChange
    {
        switch action {
        case let .rename(id, title): return try await .renamed(gateway.rename(
                token: token,
                sessionID: id,
                title: title
            ))
        case let .deleteSession(id, _, _):
            _ = try await gateway.deleteSession(token: token, sessionID: id); return .deletedSession(id)
        case let .deleteMessages(id, ids):
            _ = try await gateway.deleteMessages(token: token, ids: ids.sorted()); return .deletedMessages(id, ids)
        }
    }

    private func valid(_ action: ChatAction) -> Bool {
        guard knownSession(action.sessionID) else { return false }
        guard case let .deleteMessages(id, ids) = action else { return true }
        return library.state.selected?.sessionID == id && ids.isSubset(of: Set(library.state.messages.items.map(\.id)))
    }

    private func knownSession(_ id: String) -> Bool {
        library.state.conversations.items.contains { $0.sessionID == id } ||
            (library.state.selected?.sessionID == id && !library.state.messages.items.isEmpty)
    }

    private func title(_ id: String) -> String {
        library.state.conversations.items.first { $0.sessionID == id }?.title ??
            (library.state.selected?.sessionID == id ? library.state.selected?.title : nil) ?? ""
    }

    private var current: Bool {
        !closed && state.account != nil && state.account == library.state.account && state.account == turn.state.account
    }

    deinit { task?.cancel() }
}

private func actionFailure(_ error: Error) -> String {
    switch (error as? HTTPFailure)?.status {
    case 404: "对话不存在或已删除，请刷新后重试。"
    case 405: "当前服务暂不支持此操作，请更新服务后重试。"
    default: "操作结果未确认，请检查连接并刷新核对后重试。"
    }
}
