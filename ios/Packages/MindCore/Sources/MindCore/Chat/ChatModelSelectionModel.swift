import Combine
import Foundation

/// Account-local, memory-only catalog and selection; request snapshots stay with the turn model.
@MainActor
public final class ChatModelSelectionModel: ObservableObject {
    @Published public private(set) var state = ChatModelState()
    private let session: SessionStore
    private let gateway: any ChatModelGateway
    private let turn: ChatTurnModel
    private var task: Task<Void, Never>?
    private var sequence: UInt64 = 0
    private var closed = false

    public init(session: SessionStore, gateway: any ChatModelGateway, turn: ChatTurnModel) {
        self.session = session; self.gateway = gateway; self.turn = turn
    }

    public func bindAccount(_ value: SessionState) {
        let account = HistoryAccount.from(value)
        guard !closed, account != state.account else { return }
        clear()
        guard let account else { return }
        state.account = account; publishSelection(); refresh()
    }

    public func select(_ id: String?, account: HistoryAccount) async {
        let actual = await HistoryAccount.from(session.state)
        guard current, actual == account, state.account == account, turn.state.editable,
              turn.state.receipt == nil else { return }
        if let id {
            guard let option = state.catalog?.models.first(where: { $0.id.utf8.elementsEqual(id.utf8) }) else { return }
            state.selected = option
        } else {
            state.selected = nil
        }
        publishSelection()
    }

    public func refresh() {
        guard current, let account = state.account, !state.loading else { return }
        sequence += 1
        let ticket = sequence, session = session, gateway = gateway
        state.loading = true; state.notice = nil
        task = Task { [weak self] in
            let result: Result<ChatModelCatalog, Error>
            do {
                result = try await .success(session.authenticated { token in
                    guard await HistoryAccount.from(session.state) == account else { throw SessionFailure.superseded }
                    try Task.checkCancellation()
                    return try await gateway.catalog(token: token)
                })
            } catch { result = .failure(error) }
            let actual = await HistoryAccount.from(session.state)
            guard let self, sequence == ticket else { return }
            guard current, actual == account else { clear(); return }
            task = nil; state.loading = false
            switch result {
            case let .success(catalog):
                state.catalog = catalog
                state.selected = catalog.models.first { $0.identity == state.selected?.identity } ?? state.selected
                state.notice = nil
            case .failure:
                state.notice = "模型目录暂不可用，请重试刷新；目录不代表模型调用可用。"
            }
            publishSelection()
        }
    }

    public func clear() {
        sequence += 1; task?.cancel(); task = nil
        if let account = state.account {
            turn.setModelSelection(account: account, model: nil, available: true)
        }
        state = ChatModelState()
    }

    public func close() {
        closed = true; clear()
    }

    private func publishSelection() {
        guard let account = state.account else { return }
        turn.setModelSelection(account: account, model: state.selectedID, available: state.available)
    }

    private var current: Bool {
        !closed && state.account != nil && state.account == turn.state.account
    }

    deinit { task?.cancel() }
}
