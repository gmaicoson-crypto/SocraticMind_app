import Foundation
@testable import MindCore

actor HistoryRead<Item: Sendable> {
    let token: String
    let cursor: HistoryCursor?
    let sessionID: String?
    private var continuation: CheckedContinuation<ChatHistoryPage<Item>, Error>?
    private var response: Result<ChatHistoryPage<Item>, Error>?
    private(set) var completed = false

    init(token: String, cursor: HistoryCursor?, sessionID: String? = nil) {
        self.token = token; self.cursor = cursor; self.sessionID = sessionID
    }

    /// Intentionally ignores cancellation so the tests exercise late successes and late failures.
    func result() async throws -> ChatHistoryPage<Item> {
        defer { completed = true }
        if let response {
            return try response.get()
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func finish(_ result: Result<ChatHistoryPage<Item>, Error>) {
        guard response == nil else { return }
        response = result
        continuation?.resume(with: result)
        continuation = nil
    }

    func succeed(_ items: [Item], cursor: HistoryCursor? = nil) {
        finish(.success(ChatHistoryPage(items: items, snapshotID: cursor?.snapshotID ?? 100, nextCursor: cursor)))
    }
}

actor QueuedHistoryGateway: ChatHistoryGateway {
    private var conversationsQueue: [HistoryRead<ConversationSummary>] = []
    private var messagesQueue: [HistoryRead<StoredChatMessage>] = []
    private var allConversations: [HistoryRead<ConversationSummary>] = []
    private var allMessages: [HistoryRead<StoredChatMessage>] = []
    var conversationCount: Int {
        conversationsQueue.count
    }

    func conversations(token: String, mode: ChatMode, limit: Int, cursor: HistoryCursor?) async throws
        -> ChatHistoryPage<ConversationSummary>
    {
        guard mode == .normal, limit == 30 else { throw SessionTestError.storage }
        let read = HistoryRead<ConversationSummary>(token: token, cursor: cursor)
        allConversations.append(read); conversationsQueue.append(read)
        return try await read.result()
    }

    func messages(token: String, sessionID: String, limit: Int, cursor: HistoryCursor?) async throws
        -> ChatHistoryPage<StoredChatMessage>
    {
        guard limit == 30 else { throw SessionTestError.storage }
        let read = HistoryRead<StoredChatMessage>(token: token, cursor: cursor, sessionID: sessionID)
        allMessages.append(read); messagesQueue.append(read)
        return try await read.result()
    }

    func popConversations() -> HistoryRead<ConversationSummary>? {
        conversationsQueue.isEmpty ? nil : conversationsQueue.removeFirst()
    }

    func popMessages() -> HistoryRead<StoredChatMessage>? {
        messagesQueue.isEmpty ? nil : messagesQueue.removeFirst()
    }

    func releasePending() async {
        for read in allConversations {
            await read.finish(.failure(CancellationError()))
        }
        for read in allMessages {
            await read.finish(.failure(CancellationError()))
        }
    }
}

@MainActor
final class HistoryHarness {
    let session: SessionStore
    let auth: FakeSessionGateway
    let gateway = QueuedHistoryGateway()
    let titles = QueuedTitlesGateway()
    let model: ChatLibraryModel

    init() throws {
        auth = try FakeSessionGateway(sessionGrant())
        session = SessionStore(gateway: auth, vault: MemoryTokenVault())
        model = ChatLibraryModel(session: session, gateway: gateway, titles: titles,
                                 titlePollDelays: Array(repeating: 0, count: 7))
    }

    func login(_ id: Int64 = 1) async throws {
        if await session.state == .uninitialized {
            try await session.restore()
        }
        try await auth.setGrant(sessionGrant(id))
        try await session.login(email: "u\(id)@example.test", password: "synthetic-password")
        await model.bindAccount(session.state)
    }

    func conversations() async throws -> HistoryRead<ConversationSummary> {
        let deadline = ContinuousClock.now.advanced(by: .seconds(2))
        while ContinuousClock.now < deadline {
            if let read = await gateway.popConversations() {
                return read
            }
            try await Task.sleep(for: .milliseconds(1))
        }
        throw SessionTestError.timeout
    }

    func messages() async throws -> HistoryRead<StoredChatMessage> {
        let deadline = ContinuousClock.now.advanced(by: .seconds(2))
        while ContinuousClock.now < deadline {
            if let read = await gateway.popMessages() {
                return read
            }
            try await Task.sleep(for: .milliseconds(1))
        }
        throw SessionTestError.timeout
    }
}

@MainActor
func withHistory(_ body: (HistoryHarness) async throws -> Void) async throws {
    let harness = try HistoryHarness()
    do {
        try await body(harness)
        harness.model.close()
        await harness.gateway.releasePending()
        await harness.titles.releasePending()
    } catch {
        harness.model.close()
        await harness.gateway.releasePending()
        await harness.titles.releasePending()
        throw error
    }
}

@MainActor
func awaitHistory(_ condition: () async -> Bool) async throws {
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while await !condition() {
        guard ContinuousClock.now < deadline else { throw SessionTestError.timeout }
        try await Task.sleep(for: .milliseconds(1))
    }
}

func historySummary(_ id: Int64, _ session: String = "a", preview: String = "内容") throws -> ConversationSummary {
    let object: [String: Any] = ["session_id": session, "mode": "normal", "topic_id": NSNull(),
                                 "node_key": "__normal__", "last_message_id": id, "last_role": "assistant",
                                 "preview": preview, "updated_at": NSNull(), "title": NSNull(),
                                 "title_status": NSNull()]
    return try JSONDecoder().decode(ConversationSummary.self, from: JSONSerialization.data(withJSONObject: object))
}

func historyMessage(_ id: Int64, _ session: String) throws -> StoredChatMessage {
    let object: [String: Any] = ["id": id, "session_id": session, "mode": "normal", "topic_id": NSNull(),
                                 "node_key": "__normal__", "role": "assistant", "content": "消息\(id)",
                                 "message_type": "text", "metadata": NSNull(), "created_at": NSNull(),
                                 "attachments": []]
    return try JSONDecoder().decode(StoredChatMessage.self, from: JSONSerialization.data(withJSONObject: object))
}
