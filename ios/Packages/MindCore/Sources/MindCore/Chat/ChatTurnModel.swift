import Combine
import Foundation

/// One pending turn per account. Local task cancellation never claims that the server stopped.
@MainActor
public final class ChatTurnModel: ObservableObject {
    @Published public private(set) var state = ChatTurnState()
    private let session: SessionStore
    private let gateway: any ChatTurnGateway
    private let journal: any ChatTurnJournal
    private let requestID: @Sendable () -> String
    private let pollDelays: [UInt64]
    private var task: Task<Void, Never>?
    private var ticket: UInt64 = 0
    private var closed = false
    private var historyMutation: ChatMutationLease?

    func reserveHistoryMutation(_ account: HistoryAccount) -> ChatMutationLease? {
        guard !closed, state.account == account, state.editable, state.receipt == nil else { return nil }
        let lease = ChatMutationLease(account: account)
        historyMutation = lease; state.changingHistory = true
        return lease
    }

    func releaseHistoryMutation(_ lease: ChatMutationLease, deletedSessionID: String? = nil) {
        guard historyMutation == lease else { return }
        historyMutation = nil
        guard !closed, state.account == lease.account else { return }
        if let deletedSessionID, state.target?.sessionID == deletedSessionID {
            state.target = nil; state.draft = ""; state.notice = nil
        }
        state.changingHistory = false
    }

    private var buffer = ChatTurnBuffer()
    private var published: TimeInterval = 0

    public init(session: SessionStore, gateway: any ChatTurnGateway, journal: any ChatTurnJournal,
                requestID: @escaping @Sendable () -> String = { UUID().uuidString },
                pollDelays: [UInt64] = [500_000_000, 1_000_000_000, 2_000_000_000])
    {
        self.session = session; self.gateway = gateway; self.journal = journal
        self.requestID = requestID; self.pollDelays = pollDelays
    }

    public func bindAccount(_ value: SessionState) {
        let account = HistoryAccount.from(value)
        guard !closed, account != state.account else { return }
        clear()
        guard let account else { return }
        state.account = account
        launch { try await self.restore($0) }
    }

    public func clear() {
        historyMutation = nil
        ticket += 1
        task?.cancel(); task = nil
        buffer = ChatTurnBuffer()
        state = ChatTurnState()
    }

    public func close() {
        closed = true; clear()
    }

    public func select(_ target: ChatTarget?) {
        guard !closed, state.editable, state.target != target else { return }
        state.target = target; state.draft = ""; state.notice = nil
    }

    /// Keep completion until the history owner consumes it, even when observation skips intermediate states.
    public func acknowledge(_ receipt: ChatTurnReceipt) {
        guard !closed, state.receipt == receipt else { return }
        state.receipt = nil
    }

    public func edit(_ value: String) {
        guard !closed, state.editable else { return }
        state.draft = value; state.notice = nil
    }

    /// Compare-and-send keeps stale taps from replacing a newer draft or target.
    func sendSuggestion(account: HistoryAccount, target: ChatTarget, text: String,
                        style: String, expectedDraft: String) -> Bool
    {
        guard !closed, state.canRegenerate, state.account == account, state.target == target,
              state.draft == expectedDraft,
              (try? ChatTurnRequest(pending: PendingChatTurn(ownerID: account.userID, target: target,
                                                             requestID: "suggestion-check"),
                                    input: text, style: style)) != nil else { return false }
        state.draft = text; start(style: style, regeneration: nil)
        let started = state.pending != nil
        if !started {
            state.draft = expectedDraft
        }
        return started
    }

    public func send(style: String) {
        start(style: style, regeneration: nil)
    }

    public func regenerate(history: ChatLibraryState, style: String) {
        guard let candidate = ChatRegeneration.from(history) else { return }
        start(style: style, regeneration: candidate)
    }

    private func start(style: String, regeneration: ChatRegeneration?) {
        guard !closed, let account = state.account, let target = state.target else { return }
        if let regeneration {
            guard state.canRegenerate, regeneration.account == account, regeneration.target == target else { return }
        } else if !state.canSend {
            return
        }
        let request: ChatTurnRequest
        do {
            request = try ChatTurnRequest(
                pending: PendingChatTurn(ownerID: account.userID, target: target, requestID: requestID(),
                                         regenerateMessageID: regeneration?.answerID),
                input: regeneration?.input ?? state.draft, style: style
            )
        } catch { state.notice = "输入或会话配置无效，请检查后重试。"; return }
        state.phase = .preparing; state.pending = request.pending; state.receipt = nil
        launch { operation in
            do { try await self.journal.save(request.pending) }
            catch {
                try await self.requireCurrent(operation)
                self.state.phase = .storageFailed
                self.state.notice = "恢复记录保存失败，尚未发送。请重试读取。"
                return
            }
            try await self.requireCurrent(operation)
            self.state.phase = .sending
            if regeneration == nil {
                self.state.draft = ""
            }
            self.state.submitted = request.input
            self.state.partial = ""; self.state.ids = nil; self.buffer = ChatTurnBuffer(); self.published = 0
            let gateway = self.gateway
            do {
                try await self.authenticated(operation) { token in
                    try await gateway.stream(token: token, request: request) { event in
                        try await self.receive(event, operation: operation)
                    }
                }
            } catch {
                try await self.requireCurrent(operation)
                if regeneration != nil, let failure = error as? HTTPFailure, [400, 409].contains(failure.status),
                   ["CHAT_REGENERATE_INVALID", "CHAT_REGENERATE_NOT_LATEST"].contains(failure.code ?? "")
                {
                    // Persist a stop tombstone before clearing the rejected stale request's recovery record.
                    let remote = try await self.authenticated(operation) {
                        try await gateway.cancel(token: $0, pending: request.pending)
                    }
                    try await self.finish(operation, pending: request.pending, remote: remote)
                    self.state.notice = "原问题已变化或不再是最后一问，请刷新历史后重试。"
                    return
                }
            }
            self.state.partial = self.buffer.content; self.state.ids = self.buffer.ids
            try await self.verify(operation, pending: request.pending)
        }
    }

    public func verify() {
        guard !closed, state.canVerify else { return }
        if state.phase == .storageFailed {
            state.phase = .restoring
            launch { try await self.restore($0) }
        } else if let pending = state.pending {
            state.phase = .verifying
            launch { try await self.verify($0, pending: pending) }
        }
    }

    public func stop() {
        guard !closed, state.canStop, let pending = state.pending else { return }
        state.phase = .stopping; state.notice = "正在确认停止…"
        let gateway = gateway
        launch { operation in
            let remote = try await self
                .authenticated(operation) { try await gateway.cancel(token: $0, pending: pending) }
            try await self.finish(operation, pending: pending, remote: remote)
        }
    }

    private func restore(_ operation: UInt64) async throws {
        try await requireCurrent(operation)
        guard let account = state.account else { throw CancellationError() }
        let pending: PendingChatTurn?
        do { pending = try await journal.read(ownerID: account.userID) }
        catch {
            try await requireCurrent(operation)
            state.phase = .storageFailed; state.notice = "无法读取恢复记录，请重试；当前禁止发送。"
            return
        }
        try await requireCurrent(operation)
        state.pending = pending; state.target = pending?.target ?? state.target
        state.phase = pending == nil ? .ready : .verifying; state.notice = nil
        if let pending {
            try await verify(operation, pending: pending)
        }
    }

    private func receive(_ event: ChatEvent, operation: UInt64) async throws {
        try await requireCurrent(operation)
        try buffer.accept(event)
        let now = ProcessInfo.processInfo.systemUptime
        if now - published >= 0.05 || state.ids != buffer.ids {
            state.partial = buffer.content; state.ids = buffer.ids; published = now
        }
    }

    private func verify(_ operation: UInt64, pending: PendingChatTurn) async throws {
        try await requireCurrent(operation)
        state.phase = .verifying; state.notice = "正在核对服务端状态…"
        let gateway = gateway
        for attempt in 0 ... pollDelays.count {
            let remote: RemoteChatTurn
            do { remote = try await authenticated(operation) { try await gateway.status(token: $0, pending: pending) } }
            catch let error as HTTPFailure where error.status == 409 && error.code == "CHAT_REQUEST_DELETED" {
                try await finish(operation, pending: pending, remote: nil)
                return
            }
            if remote.status.terminal {
                try await finish(operation, pending: pending, remote: remote); return
            }
            if attempt < pollDelays.count {
                try await Task.sleep(nanoseconds: pollDelays[attempt])
            }
        }
        try await requireCurrent(operation)
        state.phase = .unresolved; state.notice = "服务仍在处理，可稍后核对或停止。不会自动重发。"
    }

    private func finish(_ operation: UInt64, pending: PendingChatTurn, remote: RemoteChatTurn?) async throws {
        guard remote == nil || remote?.status.terminal == true else { throw ChatTurnFailure.invalidResponse }
        let messages: [StoredChatMessage]
        if let ids = remote?.ids {
            guard state.ids == nil || state.ids == ids,
                  ids.ai != pending.regenerateMessageID else { throw ChatTurnFailure.invalidResponse }
            let gateway = gateway
            messages = try await authenticated(operation) { try await gateway.messages(
                token: $0,
                pending: pending,
                ids: ids
            ) }
        } else {
            messages = []
        }
        try await requireCurrent(operation)
        do { try await journal.clear(pending) }
        catch {
            try await requireCurrent(operation)
            state.phase = .storageFailed; state.notice = "结果已确认，恢复记录清理失败，请重试读取。"
            state.receipt = ChatTurnReceipt(pending: pending, status: remote?.status, messages: messages)
            return
        }
        try await requireCurrent(operation)
        state.notice = if pending.regenerateMessageID != nil, remote?.status == .interrupted {
            "重新生成已停止，原回答仍保留。"
        } else if pending.regenerateMessageID != nil, remote?.status == .failed {
            "重新生成失败，原回答仍保留。"
        } else if remote == nil || (remote?.ids != nil && messages.count != 2) {
            "消息已更新或删除，请刷新历史查看。"
        } else {
            switch remote?.status {
            case .complete: nil
            case .interrupted: "回复已停止；已保存的部分可在历史中查看。"
            default: "本次回复失败；可查看已有内容后重新输入。"
            }
        }
        state.phase = .ready; state.pending = nil; state.submitted = ""; state.partial = ""; state.ids = nil
        state.receipt = ChatTurnReceipt(pending: pending, status: remote?.status, messages: messages)
        buffer = ChatTurnBuffer()
    }

    private func launch(_ operation: @escaping @MainActor (UInt64) async throws -> Void) {
        task?.cancel(); ticket += 1
        let id = ticket
        task = Task { [weak self] in
            do { try await operation(id) }
            catch {
                guard let self, ticket == id else { return }
                let actual = await HistoryAccount.from(session.state)
                guard ticket == id else { return }
                guard state.account == actual else { clear(); return }
                if !(error is CancellationError) {
                    state.phase = .unresolved
                    state.notice = "结果尚未确认，请检查连接后核对或再次停止。不会自动重发。"
                }
            }
        }
    }

    private func authenticated<T: Sendable>(
        _ operation: UInt64, action: @escaping @Sendable (String) async throws -> T
    ) async throws -> T {
        try await requireCurrent(operation)
        let result = try await session.authenticated { token in
            try await self.requireCurrent(operation)
            return try await action(token)
        }
        try await requireCurrent(operation)
        return result
    }

    private func requireCurrent(_ operation: UInt64) async throws {
        try Task.checkCancellation()
        let actual = await HistoryAccount.from(session.state)
        guard !closed, ticket == operation, state.account != nil, state.account == actual else {
            throw CancellationError()
        }
    }

    deinit { task?.cancel() }
}
