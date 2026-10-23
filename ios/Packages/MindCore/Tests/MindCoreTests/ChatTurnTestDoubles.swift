import Foundation
@testable import MindCore

actor MemoryTurnJournal: ChatTurnJournal {
    var records: [Int64: PendingChatTurn] = [:]
    private var failRead = false, failSave = false, failAfter = false, failClear = false, failAfterClear = false

    func failures(
        read: Bool = false,
        save: Bool = false,
        after: Bool = false,
        clear: Bool = false,
        afterClear: Bool = false
    ) {
        failRead = read; failSave = save; failAfter = after; failClear = clear
        failAfterClear = afterClear
    }

    func read(ownerID: Int64) throws -> PendingChatTurn? {
        if failRead {
            throw SessionTestError.storage
        }
        return records[ownerID]
    }

    func save(_ pending: PendingChatTurn) throws {
        if failSave {
            throw SessionTestError.storage
        }
        guard records[pending.ownerID] == nil || records[pending.ownerID] == pending else {
            throw ChatTurnFailure.journalConflict
        }
        records[pending.ownerID] = pending
        if failAfter {
            throw SessionTestError.storage
        }
    }

    func clear(_ pending: PendingChatTurn) throws {
        if failClear {
            throw SessionTestError.storage
        }
        guard records[pending.ownerID] == pending else { throw ChatTurnFailure.journalConflict }
        records.removeValue(forKey: pending.ownerID)
        if failAfterClear {
            throw SessionTestError.storage
        }
    }
}

actor TurnRead<Value: Sendable> {
    let token: String
    let pending: PendingChatTurn
    private var continuation: CheckedContinuation<Value, Error>?
    private var response: Result<Value, Error>?
    private(set) var completed = false

    init(token: String, pending: PendingChatTurn) {
        self.token = token; self.pending = pending
    }

    /// Intentionally noncooperative: a cancelled operation must still reject late successes / failures.
    func result() async throws -> Value {
        defer { completed = true }
        if let response {
            return try response.get()
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func finish(_ result: Result<Value, Error>) {
        guard response == nil else { return }
        response = result; continuation?.resume(with: result); continuation = nil
    }
}

struct TurnStream: Sendable {
    let request: ChatTurnRequest
    let saved: PendingChatTurn?
    let events: AsyncThrowingStream<ChatEvent, Error>
    let continuation: AsyncThrowingStream<ChatEvent, Error>.Continuation
    init(request: ChatTurnRequest, saved: PendingChatTurn?) {
        self.request = request; self.saved = saved
        (events, continuation) = AsyncThrowingStream.makeStream()
    }
}

actor QueuedTurnGateway: ChatTurnGateway {
    let journal: MemoryTurnJournal
    private var streams: [TurnStream] = []
    private var statuses: [TurnRead<RemoteChatTurn>] = []
    private var cancels: [TurnRead<RemoteChatTurn>] = []
    private var messageReads: [TurnRead<[StoredChatMessage]>] = []
    private var cleanup: [@Sendable () async -> Void] = []
    var streamCount: Int {
        streams.count
    }

    var messageCount: Int {
        messageReads.count
    }

    var statusCount: Int {
        statuses.count
    }

    init(journal: MemoryTurnJournal) {
        self.journal = journal
    }

    func stream(token _: String, request: ChatTurnRequest,
                onEvent: @Sendable (ChatEvent) async throws -> Void) async throws
    {
        let read = try await TurnStream(request: request, saved: journal.read(ownerID: request.pending.ownerID))
        streams.append(read)
        cleanup.append { read.continuation.finish() }
        for try await event in read.events {
            try await onEvent(event)
        }
    }

    func status(token: String, pending: PendingChatTurn) async throws -> RemoteChatTurn {
        let read = TurnRead<RemoteChatTurn>(token: token, pending: pending)
        statuses.append(read); cleanup.append { await read.finish(.failure(CancellationError())) }
        return try await read.result()
    }

    func cancel(token: String, pending: PendingChatTurn) async throws -> RemoteChatTurn {
        let read = TurnRead<RemoteChatTurn>(token: token, pending: pending)
        cancels.append(read); cleanup.append { await read.finish(.failure(CancellationError())) }
        return try await read.result()
    }

    func messages(token: String, pending: PendingChatTurn, ids _: ChatMessageIDs) async throws -> [StoredChatMessage] {
        let read = TurnRead<[StoredChatMessage]>(token: token, pending: pending)
        messageReads.append(read); cleanup.append { await read.finish(.failure(CancellationError())) }
        return try await read.result()
    }

    func popStream() -> TurnStream? {
        streams.isEmpty ? nil : streams.removeFirst()
    }

    func popStatus() -> TurnRead<RemoteChatTurn>? {
        statuses.isEmpty ? nil : statuses.removeFirst()
    }

    func popCancel() -> TurnRead<RemoteChatTurn>? {
        cancels.isEmpty ? nil : cancels.removeFirst()
    }

    func popMessages() -> TurnRead<[StoredChatMessage]>? {
        messageReads.isEmpty ? nil : messageReads.removeFirst()
    }

    func close() async {
        for action in cleanup {
            await action()
        }
    }
}

@MainActor
final class TurnHarness {
    let auth: FakeSessionGateway
    let session: SessionStore
    let gateway: QueuedTurnGateway
    let journal: MemoryTurnJournal
    let model: ChatTurnModel

    init(journal: MemoryTurnJournal) throws {
        self.journal = journal
        auth = try FakeSessionGateway(sessionGrant())
        session = SessionStore(gateway: auth, vault: MemoryTokenVault())
        gateway = QueuedTurnGateway(journal: journal)
        model = ChatTurnModel(session: session, gateway: gateway, journal: journal,
                              requestID: { "turn-contract-id" }, pollDelays: [])
    }

    func login(_ id: Int64 = 1) async throws {
        if await session.state == .uninitialized {
            try await session.restore()
        }
        try await auth.setGrant(sessionGrant(id))
        try await session.login(email: "u\(id)@example.test", password: "synthetic-password")
        await model.bindAccount(session.state)
    }

    func ready() async throws {
        try await awaitHistory { self.model.state.editable }
        try model.select(turnRequest().pending.target)
        try model.edit(turnRequest().input)
    }

    func begin() async throws -> TurnStream {
        model.send(style: "标准")
        return try await nextTurn { await self.gateway.popStream() }
    }

    func status() async throws -> TurnRead<RemoteChatTurn> {
        try await nextTurn { await self.gateway.popStatus() }
    }

    func cancel() async throws -> TurnRead<RemoteChatTurn> {
        try await nextTurn { await self.gateway.popCancel() }
    }

    func resolve(_ read: TurnRead<RemoteChatTurn>, status: ChatTurnStatus = .complete) async throws {
        try await read.finish(.success(RemoteChatTurn(status: status, ids: ChatMessageIDs(user: 101, ai: 102))))
        let message = try await nextTurn { await self.gateway.popMessages() }
        try await message.finish(.success(turnFixture().messages))
        try await awaitHistory { [.ready, .storageFailed].contains(self.model.state.phase) }
    }

    func close() async {
        model.close(); await gateway.close()
    }
}

@MainActor
func withTurn(
    _ journal: MemoryTurnJournal = MemoryTurnJournal(),
    _ body: (TurnHarness) async throws -> Void
) async throws {
    let harness = try TurnHarness(journal: journal)
    do { try await body(harness); await harness.close() }
    catch { await harness.close(); throw error }
}

@MainActor
func nextTurn<Value: Sendable>(_ pop: () async -> Value?) async throws -> Value {
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while ContinuousClock.now < deadline {
        if let value = await pop() {
            return value
        }
        try await Task.sleep(for: .milliseconds(1))
    }
    throw SessionTestError.timeout
}
