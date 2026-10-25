import CryptoKit
import Foundation
@testable import MindCore

actor AvatarWrite {
    let kind: String
    let ownerID: Int64?
    let sessionID: String
    let data: Data
    private var continuation: CheckedContinuation<ChatAvatarResource?, Error>?
    private var response: Result<ChatAvatarResource?, Error>?
    private(set) var completed = false

    init(_ kind: String, ownerID: Int64? = nil, sessionID: String, data: Data = Data()) {
        self.kind = kind; self.ownerID = ownerID; self.sessionID = sessionID; self.data = data
    }

    func result() async throws -> ChatAvatarResource? {
        defer { completed = true }
        if let response {
            return try response.get()
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func finish(_ value: Result<ChatAvatarResource?, Error>) {
        guard response == nil else { return }
        response = value; continuation?.resume(with: value); continuation = nil
    }
}

actor QueuedAvatarGateway: ChatAvatarGateway {
    private var calls: [AvatarWrite] = []
    private var pending: [AvatarWrite] = []
    private(set) var count = 0

    func upload(token _: String, ownerID: Int64, sessionID: String, data: Data,
                format _: AvatarImageFormat) async throws -> ChatAvatarResource
    {
        let call = write(AvatarWrite("upload", ownerID: ownerID, sessionID: sessionID, data: data))
        guard let result = try await call.result() else { throw SessionTestError.storage }; return result
    }

    func delete(token _: String, sessionID: String) async throws -> Int64 {
        _ = try await write(AvatarWrite("delete", sessionID: sessionID)).result(); return 1
    }

    func image(_: ChatAvatarResource) async throws -> Data {
        throw SessionTestError.storage
    }

    private func write(_ call: AvatarWrite) -> AvatarWrite {
        count += 1; calls.append(call); pending.append(call); return call
    }

    func pop() -> AvatarWrite? {
        calls.isEmpty ? nil : calls.removeFirst()
    }

    func close() async {
        for call in pending {
            await call.finish(.failure(CancellationError()))
        }
    }
}

actor MemoryAvatarStore: ChatAvatarStore {
    private var values: [Int64: ChatAvatarChoices] = [:]
    var readFailure = false
    var writeFailure = false
    var failAfterWrite = false
    private(set) var writes = 0
    private var readGate: AvatarWrite?
    private var readGates: [AvatarWrite] = []
    private(set) var reads = 0
    private var afterWrite: (@Sendable () async -> Void)?

    func onWrite(_ action: @escaping @Sendable () async -> Void) {
        afterWrite = action
    }

    func configure(readFailure: Bool = false, writeFailure: Bool = false, failAfterWrite: Bool = false) {
        self.readFailure = readFailure; self.writeFailure = writeFailure; self.failAfterWrite = failAfterWrite
    }

    func gateReads(_ gate: AvatarWrite?) {
        readGate = gate
        if let gate {
            readGates.append(gate)
        }
    }

    func releaseReads() async {
        for gate in readGates {
            await gate.finish(.success(nil))
        }
    }

    func seed(_ owner: Int64, _ id: String, _ resource: ChatAvatarResource) throws {
        values[owner] = try (values[owner] ?? ChatAvatarChoices()).replacing(id, with: resource)
    }

    func read(ownerID: Int64) async throws -> ChatAvatarChoices {
        let result = try values[ownerID] ?? ChatAvatarChoices()
        reads += 1
        if let readGate {
            _ = try await readGate.result()
        }
        if readFailure {
            throw SessionTestError.storage
        }; return result
    }

    func replace(
        ownerID: Int64,
        sessionID: String,
        expected: ChatAvatarResource?,
        value: ChatAvatarResource?
    ) async throws {
        writes += 1
        if writeFailure {
            throw SessionTestError.storage
        }
        let old = try values[ownerID] ?? ChatAvatarChoices()
        guard old[sessionID] == expected else { throw ChatAvatarFailure.conflict }
        values[ownerID] = try old.replacing(sessionID, with: value)
        if let afterWrite {
            self.afterWrite = nil; await afterWrite()
        }
        if failAfterWrite {
            throw SessionTestError.storage
        }
    }

    func clear(ownerID: Int64) {
        values.removeValue(forKey: ownerID)
    }
}

actor AvatarAccountReader {
    private let session: SessionStore
    private var gate: AvatarWrite?
    private(set) var captured = false

    init(_ session: SessionStore) {
        self.session = session
    }

    func holdNext(_ gate: AvatarWrite) {
        self.gate = gate
    }

    func read() async -> HistoryAccount? {
        let snapshot = await HistoryAccount.from(session.state)
        if let gate {
            self.gate = nil; captured = true
            _ = try? await gate.result()
        }
        return snapshot
    }
}

@MainActor
final class AvatarHarness {
    let base: ActionsHarness
    let store = MemoryAvatarStore()
    let gateway = QueuedAvatarGateway()
    let model: ChatAvatarModel
    let accountReader: AvatarAccountReader

    init(controlAccountSnapshots: Bool = false) throws {
        var avatar: ChatAvatarModel?
        let base = try ActionsHarness { account, id in
            await avatar?.forgetDeletedSession(account: account, sessionID: id)
        }
        self.base = base
        let reader = AvatarAccountReader(base.session)
        accountReader = reader
        let model = if controlAccountSnapshots {
            ChatAvatarModel(session: base.session, gateway: gateway, store: store,
                            library: base.history.model, turn: base.turn,
                            accountSnapshot: { await reader.read() })
        } else {
            ChatAvatarModel(session: base.session, gateway: gateway, store: store,
                            library: base.history.model, turn: base.turn)
        }
        self.model = model; avatar = model
    }

    func login(_ id: Int64 = 1) async throws {
        model.clear(); try await base.login(id)
        await model.bindAccount(base.session.state)
        try await awaitHistory { !self.model.state.loading }
    }

    func picker() throws -> ChatAvatarPicker {
        guard let target = base.history.model.state.selected?.target else { throw SessionTestError.storage }
        model.open(target)
        guard let picker = model.state.picker else { throw SessionTestError.storage }; return picker
    }

    func idle() async throws {
        try await awaitHistory { !self.model.state.busy && !self.model.state.loading }
    }

    func next() async throws -> AvatarWrite {
        try await nextTurn { await self.gateway.pop() }
    }

    func close() async {
        model.close(); await base.close(); await gateway.close(); await store.releaseReads()
    }
}

@MainActor
func withAvatar(controlAccountSnapshots: Bool = false, _ body: (AvatarHarness) async throws -> Void) async throws {
    let harness = try AvatarHarness(controlAccountSnapshots: controlAccountSnapshots)
    do { try await body(harness); await harness.close() }
    catch { await harness.close(); throw error }
}

func uploadedAvatar(_ ownerID: Int64 = 1, id: String = "main", version: Character = "a") throws -> ChatAvatarResource {
    let hash = SHA256.hash(data: Data(id.utf8)).map { String(format: "%02x", $0) }.joined().prefix(24)
    return try ChatAvatarResource(
        "/static/avatars/ai_\(ownerID)_\(hash)_\(String(repeating: String(version), count: 32)).png"
    )
}
