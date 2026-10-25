import Foundation
@testable import MindCore

actor ActionWrite {
    let token: String
    let kind: String
    let sessionID: String?
    let title: String?
    let ids: [Int64]
    private var continuation: CheckedContinuation<ChatTitle?, Error>?
    private var response: Result<ChatTitle?, Error>?
    private(set) var completed = false

    init(token: String, kind: String, sessionID: String? = nil, title: String? = nil, ids: [Int64] = []) {
        self.token = token; self.kind = kind; self.sessionID = sessionID; self.title = title; self.ids = ids
    }

    /// Intentionally non-cooperative so account and sequence checks must reject late results.
    func result() async throws -> ChatTitle? {
        defer { completed = true }
        if let response {
            return try response.get()
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func finish(_ value: Result<ChatTitle?, Error>) {
        guard response == nil else { return }
        response = value; continuation?.resume(with: value); continuation = nil
    }
}

actor QueuedActionsGateway: ChatActionsGateway {
    private var calls: [ActionWrite] = []
    private var pending: [ActionWrite] = []
    private(set) var count = 0
    func title(token _: String, sessionID _: String) async throws -> ChatTitle? {
        throw SessionTestError.storage
    }

    func rename(token: String, sessionID: String, title: String) async throws -> ChatTitle {
        let call = write(ActionWrite(token: token, kind: "rename", sessionID: sessionID, title: title))
        guard let value = try await call.result() else { throw SessionTestError.storage }; return value
    }

    func deleteSession(token: String, sessionID: String) async throws -> Int64 {
        _ = try await write(ActionWrite(token: token, kind: "session", sessionID: sessionID)).result(); return 2
    }

    func deleteMessages(token: String, ids: [Int64]) async throws -> Int64 {
        _ = try await write(ActionWrite(token: token, kind: "messages", ids: ids)).result(); return Int64(ids.count)
    }

    private func write(_ value: ActionWrite) -> ActionWrite {
        count += 1; calls.append(value); pending.append(value); return value
    }

    func pop() -> ActionWrite? {
        calls.isEmpty ? nil : calls.removeFirst()
    }

    func close() async {
        for call in pending {
            await call.finish(.failure(CancellationError()))
        }
    }
}

@MainActor
final class ActionsHarness {
    let history: HistoryHarness
    var session: SessionStore {
        history.session
    }

    let journal = MemoryTurnJournal()
    let turnGateway: QueuedTurnGateway
    let turn: ChatTurnModel
    let gateway = QueuedActionsGateway()
    let model: ChatActionsModel

    init(onSessionDeleted: @escaping @MainActor (HistoryAccount, String) async -> String? = { _, _ in nil }) throws {
        let history = try HistoryHarness()
        self.history = history
        let turnGateway = QueuedTurnGateway(journal: journal)
        self.turnGateway = turnGateway
        let turn = ChatTurnModel(session: history.session, gateway: turnGateway, journal: journal, pollDelays: [])
        self.turn = turn
        model = ChatActionsModel(session: history.session, gateway: gateway, library: history.model, turn: turn,
                                 onSessionDeleted: onSessionDeleted)
    }

    func login(_ id: Int64 = 1) async throws {
        if case .signedIn = await session.state {
            model.clear(); history.model.clear(); turn.clear()
            try await session.logout()
        }
        try await history.login(id)
        await turn.bindAccount(session.state); await model.bindAccount(session.state)
        try await history.conversations().succeed([historySummary(104, "main"), historySummary(90, "other")])
        try await awaitHistory { self.history.model.state.conversations.loaded && self.turn.state.editable }
        history.model.selectConversation("main")
        try await history.messages().succeed((101 ... 104).reversed().map { try historyMessage(Int64($0), "main") })
        try await awaitHistory { self.history.model.state.messages.loaded }
        turn.select(history.model.state.selected?.target); turn.edit("未发送的草稿")
    }

    func next() async throws -> ActionWrite {
        try await nextTurn { await self.gateway.pop() }
    }

    func close() async {
        model.close(); turn.close(); history.model.close()
        await history.gateway.releasePending(); await gateway.close(); await turnGateway.close()
    }
}

@MainActor
func withActions(_ body: (ActionsHarness) async throws -> Void) async throws {
    let harness = try ActionsHarness()
    do { try await body(harness); await harness.close() }
    catch { await harness.close(); throw error }
}

func manualTitle(_ value: String = "手动标题") throws -> ChatTitle {
    try JSONDecoder().decode(ChatTitle.self, from: JSONSerialization.data(withJSONObject: [
        "session_id": "main", "title": value, "status": "manual", "retry_pending": false,
    ]))
}
