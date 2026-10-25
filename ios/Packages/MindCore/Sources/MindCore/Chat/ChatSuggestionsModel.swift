import Combine
import Foundation

/// Suggestion presentation and finite reads only; reuse the history and durable send owners.
@MainActor
public final class ChatSuggestionsModel: ObservableObject {
    @Published public private(set) var state = ChatSuggestionsState()
    private let session: SessionStore
    private let gateway: any ChatSuggestionsGateway
    private let history: ChatLibraryModel
    private let turn: ChatTurnModel
    private var cache = ChatSuggestionsCache()
    private var owner: HistoryAccount?
    private var active = false
    private var closed = false
    private var attempted = false
    private var sequence: UInt64 = 0
    private var request: Task<Void, Never>?
    private var observation: AnyCancellable?
    private var sessionObservation: Task<Void, Never>?
    private var sessionAccount: HistoryAccount?

    public init(session: SessionStore, gateway: any ChatSuggestionsGateway,
                history: ChatLibraryModel, turn: ChatTurnModel)
    {
        self.session = session; self.gateway = gateway; self.history = history; self.turn = turn
        sessionObservation = Task { [weak self] in
            for await value in await session.updates() {
                guard !Task.isCancelled, let self else { return }
                sessionAccount = HistoryAccount.from(value); synchronize()
            }
        }
        observation = Publishers.CombineLatest(history.$state, turn.$state).sink { [weak self] _, _ in
            // Published emits before storing; always re-read both current owners on the main actor.
            Task { @MainActor [weak self] in self?.synchronize() }
        }
    }

    public func setActive(_ value: Bool) {
        active = value; synchronize()
    }

    public func setModel(_ value: String?) {
        if let account = turn.state.account {
            turn.setModelSelection(account: account, model: value, available: true)
        }
        synchronize()
    }

    public func clear() {
        cancelRead(); owner = nil; cache.clear(); attempted = false; state = ChatSuggestionsState()
    }

    public func close() {
        closed = true; clear(); observation?.cancel(); observation = nil; sessionObservation?
            .cancel(); sessionObservation = nil
    }

    public func refresh() {
        synchronize(autoLoad: false)
        guard state.enabled, !state.loading, state.choice == nil else { return }
        load(excluded: state.items)
    }

    public func choose(_ text: String, context: ChatSuggestionContext, style: String) async {
        let actual = await HistoryAccount.from(session.state)
        sessionAccount = actual
        guard actual != nil, actual == history.state.account else { clear(); return }
        synchronize(autoLoad: false)
        guard state.enabled, state.context == context, state.items.contains(text) else { return }
        let draft = turn.state.draft
        if !draft.isEmpty {
            cancelRead()
            state.choice = ChatSuggestionChoice(text: text, draft: draft)
        } else {
            send(text, style: style, draft: draft)
        }
    }

    public func cancelChoice() {
        state.choice = nil
    }

    public func confirmChoice(style: String) {
        guard let choice = state.choice, let context = state.context else { return }
        state.choice = nil; attempted = true
        // Capture the explicit confirmation before the system dismisses the alert binding.
        Task { [weak self] in
            guard let self else { return }
            let actual = await HistoryAccount.from(session.state)
            sessionAccount = actual; synchronize(autoLoad: false)
            guard actual == context.account, state.enabled, state.context == context, state.items.contains(choice.text),
                  choice.draft == turn.state.draft else { return }
            send(choice.text, style: style, draft: choice.draft)
        }
    }

    private func send(_ text: String, style: String, draft: String) {
        guard let context = state.context else { return }
        if turn.sendSuggestion(account: context.account, target: context.target, text: text,
                               style: style, expectedDraft: draft, model: context.model)
        {
            cancelRead(); state.enabled = false; state.choice = nil
        }
    }

    private func synchronize(autoLoad: Bool = true) {
        guard !closed else { return }
        let h = history.state, t = turn.state
        let account = h.account == sessionAccount ? h.account : nil
        if account != owner {
            cancelRead(); cache.clear(); owner = account; state = ChatSuggestionsState(); attempted = false
        }
        let context = account == nil ? nil : ChatSuggestionContext.from(h, t, model: t.model)
        let enabled = active && context != nil && t.modelAvailable && t.editable && t.receipt == nil && h.messages
            .loading == nil
        if context != state.context {
            cancelRead(); attempted = false; state = ChatSuggestionsState()
            state.context = context; state.items = context.map { ChatSuggestionDefaults.items($0) } ?? []
        }
        if !enabled {
            cancelRead()
        }
        if !enabled || state.choice?.draft != t.draft {
            state.choice = nil
        }
        state.enabled = enabled
        if autoLoad, enabled, !attempted, state.choice == nil, let context,
           context.hasConversation || (context.target.mode == .socratic && context.target.topicID > 0)
        {
            if let saved = cache.get(context) {
                attempted = true; state.items = saved.items; state.source = saved.source
            } else {
                load(excluded: [])
            }
        }
    }

    private func cancelRead() {
        sequence += 1; request?.cancel(); request = nil
        if state.loading {
            attempted = false
        }
        state.loading = false
    }

    private func load(excluded: [String]) {
        guard let context = state.context else { return }
        cancelRead(); attempted = true; sequence += 1; let ticket = sequence
        state.loading = true; state.notice = nil; state.choice = nil
        let session = session, gateway = gateway
        request = Task { [weak self] in
            let response: Result<ChatSuggestions, Error>
            do {
                let result = try await session.authenticated { token in
                    guard await HistoryAccount.from(session.state) == context.account
                    else { throw SessionFailure.superseded }
                    try Task.checkCancellation()
                    return try await gateway.suggestions(token: token, target: context.target,
                                                         exclude: excluded, model: context.model)
                }
                try Task.checkCancellation(); response = .success(result)
            } catch { response = .failure(error) }
            let actual = await HistoryAccount.from(session.state)
            guard let self else { return }
            synchronize()
            guard sequence == ticket, state.context == context else { return }
            request = nil
            guard actual == context.account else { sessionAccount = actual; clear(); return }
            let result: ChatSuggestions?
            var failed = false
            switch response {
            case let .success(value): result = value
            case let .failure(error):
                if error is CancellationError {
                    state.loading = false; attempted = false; return
                }
                result = nil; failed = true
            }
            let fresh = result?.items.filter { !excluded.contains($0) } ?? []
            let items = fresh.isEmpty ? ChatSuggestionDefaults.items(context, excluding: excluded) : fresh
            let source = fresh.isEmpty ? SuggestionSource.local : (result?.source ?? .local)
            if let accepted = try? ChatSuggestions(items: items, source: source) {
                cache.put(context, accepted)
            }
            state.items = items; state.source = source; state.loading = false
            state.notice = failed ? "建议服务暂不可用，已显示参考话题。" : (fresh.isEmpty ? "没有更多建议，已显示参考话题。" : nil)
        }
    }

    deinit { request?.cancel(); sessionObservation?.cancel() }
}
