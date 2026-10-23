import Foundation
@testable import MindCore

actor SuggestionRead {
    let token: String
    let target: ChatTarget
    let exclude: [String]
    let model: String?
    private var continuation: CheckedContinuation<ChatSuggestions, Error>?
    private var response: Result<ChatSuggestions, Error>?
    private(set) var completed = false
    init(token: String, target: ChatTarget, exclude: [String], model: String?) {
        self.token = token; self.target = target; self.exclude = exclude; self.model = model
    }

    func result() async throws -> ChatSuggestions {
        defer { completed = true }
        if let response {
            return try response.get()
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func finish(_ value: Result<ChatSuggestions, Error>) {
        guard response == nil else { return }
        response = value; continuation?.resume(with: value); continuation = nil
    }

    func succeed(_ items: [String]) throws {
        try finish(.success(ChatSuggestions(items: items, source: .ai)))
    }
}

actor QueuedSuggestionsGateway: ChatSuggestionsGateway {
    private var calls: [SuggestionRead] = []
    private var pending: [SuggestionRead] = []
    var count: Int {
        pending.count
    }

    func suggestions(token: String, target: ChatTarget, exclude: [String],
                     model: String?) async throws -> ChatSuggestions
    {
        let read = SuggestionRead(token: token, target: target, exclude: exclude, model: model)
        pending.append(read); calls.append(read); return try await read.result()
    }

    func pop() -> SuggestionRead? {
        calls.isEmpty ? nil : calls.removeFirst()
    }

    func next() async throws -> SuggestionRead {
        let deadline = ContinuousClock.now.advanced(by: .seconds(2))
        while calls.isEmpty {
            guard ContinuousClock.now < deadline else { throw SessionTestError.timeout }
            try await Task.sleep(for: .milliseconds(1))
        }
        return calls.removeFirst()
    }

    func close() async {
        for read in pending {
            await read.finish(.failure(CancellationError()))
        }
    }
}

@MainActor
final class SuggestionsHarness {
    let base: ActionsHarness
    let gateway = QueuedSuggestionsGateway()
    let model: ChatSuggestionsModel
    init() throws {
        let base = try ActionsHarness(); self.base = base
        model = ChatSuggestionsModel(
            session: base.session,
            gateway: gateway,
            history: base.history.model,
            turn: base.turn
        )
    }

    func login(_ id: Int64 = 1, empty: Bool = false) async throws {
        try await base.login(id); base.turn.edit("")
        try await replace(empty ? [] : [suggestionMessage(104, "main")])
    }

    func replace(_ rows: [StoredChatMessage]) async throws {
        base.history.model.refreshMessages(); try await base.history.messages().succeed(rows)
        try await awaitHistory { self.base.history.model.state.messages.loading == nil }
    }

    func select(_ id: String) async throws {
        base.history.model.selectConversation(id); base.turn.select(base.history.model.state.selected?.target)
        try await base.history.messages().succeed([suggestionMessage(104, id)])
        try await awaitHistory { self.base.history.model.state.messages.loaded }
    }

    func close() async {
        model.close(); await base.close(); await gateway.close()
    }
}

@MainActor
func withSuggestions(_ body: (SuggestionsHarness) async throws -> Void) async throws {
    let h = try SuggestionsHarness()
    do { try await h.login(); try await body(h); await h.close() }
    catch { await h.close(); throw error }
}

func suggestionMessage(_ id: Int64, _ session: String, text: String = "合成话题") throws -> StoredChatMessage {
    let object: [String: Any] = ["id": id, "session_id": session, "mode": "normal", "topic_id": NSNull(),
                                 "node_key": "__normal__", "role": "user", "content": text, "message_type": "chat",
                                 "metadata": NSNull(),
                                 "created_at": NSNull(), "attachments": []]
    return try JSONDecoder().decode(StoredChatMessage.self, from: JSONSerialization.data(withJSONObject: object))
}
