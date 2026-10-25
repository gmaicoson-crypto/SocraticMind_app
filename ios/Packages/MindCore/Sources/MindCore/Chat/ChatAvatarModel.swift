import Combine
import Foundation

/// Local selection and finite writes; the turn model owns the shared mutation lease.
@MainActor
public final class ChatAvatarModel: ObservableObject {
    @Published public private(set) var state = ChatAvatarState()
    private let session: SessionStore
    private let gateway: any ChatAvatarGateway
    private let store: any ChatAvatarStore
    private let library: ChatLibraryModel
    private let turn: ChatTurnModel
    private let accountSnapshot: @Sendable () async -> HistoryAccount?
    private var task: Task<Void, Never>?
    private var lease: ChatMutationLease?
    private var sequence: UInt64 = 0
    private var closed = false

    public convenience init(session: SessionStore, gateway: any ChatAvatarGateway, store: any ChatAvatarStore,
                            library: ChatLibraryModel, turn: ChatTurnModel)
    {
        self.init(session: session, gateway: gateway, store: store, library: library, turn: turn,
                  accountSnapshot: { await HistoryAccount.from(session.state) })
    }

    init(session: SessionStore, gateway: any ChatAvatarGateway, store: any ChatAvatarStore,
         library: ChatLibraryModel, turn: ChatTurnModel,
         accountSnapshot: @escaping @Sendable () async -> HistoryAccount?)
    {
        self.session = session; self.gateway = gateway; self.store = store
        self.library = library; self.turn = turn; self.accountSnapshot = accountSnapshot
    }

    public func bindAccount(_ value: SessionState) {
        let account = HistoryAccount.from(value)
        guard !closed, state.account != account else { return }
        clear()
        guard let account else { return }
        state.account = account; reload()
    }

    public func clear() {
        sequence += 1; task?.cancel(); task = nil
        if let lease {
            turn.releaseHistoryMutation(lease)
        }
        lease = nil; state = ChatAvatarState()
    }

    public func close() {
        closed = true; clear()
    }

    public func reload() {
        guard current, let account = state.account, !state.busy, !state.loading,
              state.pendingSave == nil else { return }
        sequence += 1
        let ticket = sequence, store = store, accountSnapshot = accountSnapshot
        state.loading = true; state.notice = nil
        task = Task { [weak self] in
            let result: Result<ChatAvatarChoices, Error>
            do { result = try await .success(store.read(ownerID: account.userID)) }
            catch { result = .failure(error) }
            let actual = await accountSnapshot()
            guard let self, sequence == ticket else { return }
            guard current, actual == account else { clear(); return }
            task = nil; state.loading = false
            switch result {
            case let .success(choices): state.choices = choices
            case .failure: state.choices = nil; state.notice = "头像记录读取失败，请重试读取。"
            }
        }
    }

    public func open(_ target: ChatTarget) {
        guard available, known(target), let account = state.account else { return }
        state.picker = ChatAvatarPicker(account: account, target: target); state.notice = nil
    }

    public func dismiss() {
        guard !state.busy else { return }; state.picker = nil
    }

    public func selectPreset(_ resource: ChatAvatarResource?, picker: ChatAvatarPicker) {
        guard resource == nil || ChatAvatarResource.presets(for: picker.target.mode).contains(resource?.path ?? "")
        else { return }
        change(picker) { expected in
            ChatAvatarSave(target: picker.target, expected: expected, value: resource, clearRemote: true)
        }
    }

    public func upload(_ data: Data, format: AvatarImageFormat, picker: ChatAvatarPicker) {
        guard !data.isEmpty, data.count <= ChatAvatarResource.maximumImageBytes else {
            if state.picker == picker, current, !state.busy {
                state.notice = "请选择不超过 5 MiB 的有效图片。"
            }
            return
        }
        let session = session, gateway = gateway
        change(picker) { expected in
            let resource = try await session.authenticated { token in
                guard await HistoryAccount.from(session.state) == picker.account
                else { throw SessionFailure.superseded }
                try Task.checkCancellation()
                return try await gateway.upload(token: token, ownerID: picker.account.userID,
                                                sessionID: picker.target.sessionID, data: data, format: format)
            }
            guard resource.uploaded, try resource.belongsTo(ownerID: picker.account.userID,
                                                            sessionID: picker.target.sessionID)
            else { throw ChatAvatarFailure.invalidResource }
            return ChatAvatarSave(target: picker.target, expected: expected, value: resource, clearRemote: false)
        }
    }

    public func retrySave() {
        guard let save = state.pendingSave, let account = state.account else { return }
        start(account, retry: true) { save }
    }

    /// Abandon only the unsaved in-memory selection; never repeat a remote mutation.
    public func discardPendingSave() {
        guard current, !state.busy, state.pendingSave != nil else { return }
        state.pendingSave = nil; state.picker = nil; reload()
    }

    /// Called after a confirmed session deletion while actions retains the shared mutation lease.
    public func forgetDeletedSession(account: HistoryAccount, sessionID: String) async -> String? {
        guard current, state.account == account else { return nil }
        sequence += 1; task?.cancel(); task = nil
        let ticket = sequence
        state.loading = false; state.busy = true
        var failed = false
        var remaining: ChatAvatarChoices?
        do {
            let previous = try await store.read(ownerID: account.userID)
            try await ensureAccount(account)
            try await store.replace(
                ownerID: account.userID,
                sessionID: sessionID,
                expected: previous[sessionID],
                value: nil
            )
            remaining = try previous.replacing(sessionID, with: nil)
        } catch { failed = true }
        let actual = await accountSnapshot()
        guard sequence == ticket, current, state.account == account, actual == account else { return nil }
        let message = failed ? "对话已删除，头像本地记录清理失败。" : nil
        state.choices = remaining ?? (try? state.choices?.replacing(sessionID, with: nil))
        state.busy = false
        if state.picker?.target.sessionID.utf8.elementsEqual(sessionID.utf8) == true {
            state.picker = nil
        }
        if state.pendingSave?.target.sessionID.utf8.elementsEqual(sessionID.utf8) == true {
            state.pendingSave = nil
        }
        state.notice = message
        return message
    }

    private func change(_ picker: ChatAvatarPicker,
                        prepare: @escaping @MainActor (ChatAvatarResource?) async throws -> ChatAvatarSave)
    {
        guard available, state.picker == picker, known(picker.target) else { return }
        let expected = state.choices?[picker.target.sessionID]
        start(picker.account, retry: false) { try await prepare(expected) }
    }

    private func start(_ account: HistoryAccount, retry: Bool,
                       prepare: @escaping @MainActor () async throws -> ChatAvatarSave)
    {
        guard current, !state.busy, !state.loading, state.loaded, state.account == account,
              retry || state.pendingSave == nil, let reservation = turn.reserveHistoryMutation(account) else { return }
        lease = reservation; sequence += 1
        let ticket = sequence
        state.busy = true; state.notice = nil
        task = Task { [weak self] in
            guard let self else { return }
            var save: ChatAvatarSave?, stored = false, failure: Error?
            do {
                try await ensureAccount(account)
                let next = try await prepare()
                try await ensureAccount(account)
                save = next
                let actual = try await store.read(ownerID: account.userID)[next.target.sessionID]
                try await ensureAccount(account)
                if actual != next.value {
                    try await store.replace(ownerID: account.userID, sessionID: next.target.sessionID,
                                            expected: next.expected, value: next.value)
                }
                stored = true
                try await ensureAccount(account)
                if next.clearRemote {
                    try await clearUpload(account, sessionID: next.target.sessionID)
                }
            } catch { failure = error }
            let actual = await accountSnapshot()
            guard sequence == ticket else { return }
            turn.releaseHistoryMutation(reservation); lease = nil; task = nil
            guard current, actual == account else { clear(); return }
            state.busy = false
            if let save, stored {
                state.choices = try? state.choices?.replacing(save.target.sessionID, with: save.value)
                state.pendingSave = nil; state.picker = nil
                state.notice = failure == nil ? nil : "头像已保存，但旧上传文件清理未确认。"
            } else if let save {
                state.pendingSave = save
                state.notice = "头像选择尚未保存。可重试保存或放弃；重试不会再次上传图片。"
            } else {
                state.notice = uploadFailure(failure)
            }
        }
    }

    private func clearUpload(_ account: HistoryAccount, sessionID: String) async throws {
        let session = session, gateway = gateway
        _ = try await session.authenticated { token in
            guard await HistoryAccount.from(session.state) == account else { throw SessionFailure.superseded }
            try Task.checkCancellation()
            return try await gateway.delete(token: token, sessionID: sessionID)
        }
    }

    private func ensureAccount(_ account: HistoryAccount) async throws {
        try Task.checkCancellation()
        let actual = await accountSnapshot()
        try Task.checkCancellation()
        guard actual == account, current, state.account == account
        else { throw SessionFailure.superseded }
    }

    private var available: Bool {
        current && state.loaded && !state.loading && !state.busy && state.pendingSave == nil && turn.state.editable
    }

    private func known(_ target: ChatTarget) -> Bool {
        guard let selected = library.state.selected?.target else { return false }
        return selected == target && selected.sessionID.utf8.elementsEqual(target.sessionID.utf8)
    }

    private var current: Bool {
        !closed && state.account != nil && state.account == library.state.account && state.account == turn.state.account
    }

    deinit { task?.cancel() }
}

private func uploadFailure(_ error: Error?) -> String {
    switch (error as? HTTPFailure)?.status {
    case 400, 413, 415: "图片未被接受，请重新选择支持的图片。"
    case 429: "上传过于频繁，请稍后再试。"
    default: "上传结果未确认，旧头像文件可能已被替换。请检查连接后重新选择；不会自动重传。"
    }
}
