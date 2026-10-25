import Foundation
@testable import MindCore
import Testing

actor ModelRead {
    let token: String
    private var continuation: CheckedContinuation<ChatModelCatalog, Error>?
    private var response: Result<ChatModelCatalog, Error>?
    private(set) var completed = false
    init(token: String) {
        self.token = token
    }

    func result() async throws -> ChatModelCatalog {
        defer { completed = true }
        if let response {
            return try response.get()
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func finish(_ value: Result<ChatModelCatalog, Error>) {
        guard response == nil else { return }
        response = value; continuation?.resume(with: value); continuation = nil
    }
}

actor QueuedModelGateway: ChatModelGateway {
    private var calls: [ModelRead] = [], pending: [ModelRead] = []
    var count: Int {
        pending.count
    }

    func catalog(token: String) async throws -> ChatModelCatalog {
        let read = ModelRead(token: token)
        pending.append(read); calls.append(read)
        return try await read.result()
    }

    func pop() -> ModelRead? {
        calls.isEmpty ? nil : calls.removeFirst()
    }

    func close() async {
        for read in pending {
            await read.finish(.failure(CancellationError()))
        }
    }
}

@MainActor
final class ModelHarness {
    let base: TurnHarness
    let gateway = QueuedModelGateway()
    let model: ChatModelSelectionModel
    let catalog: ChatModelCatalog
    init() throws {
        base = try TurnHarness(journal: MemoryTurnJournal()); catalog = try modelFixture().catalog
        model = ChatModelSelectionModel(session: base.session, gateway: gateway, turn: base.model)
    }

    func login(_ id: Int64 = 1) async throws {
        if case .signedIn = await base.session.state {
            try await base.session.logout()
        }
        try await base.login(id); try await base.ready(); await model.bindAccount(base.session.state)
    }

    func read() async throws -> ModelRead {
        try await nextTurn { await self.gateway.pop() }
    }

    func loaded() async throws {
        try await read().finish(.success(catalog))
        try await awaitHistory { !self.model.state.loading }
    }

    func close() async {
        model.close(); await gateway.close(); await base.close()
    }
}

@MainActor
private func withModels(_ body: (ModelHarness) async throws -> Void) async throws {
    let h = try ModelHarness()
    do { try await h.login(); try await body(h); await h.close() }
    catch { await h.close(); throw error }
}

@MainActor
struct ChatModelSelectionModelTests {
    @Test
    func defaultStaysOmittedAndExplicitChoiceIsSnapshottedForActiveSend() async throws {
        try await withModels { h in
            h.model.refresh(); try await h.loaded()
            #expect(await h.gateway.count == 1)
            #expect(h.model.state.selectedID == nil && h.base.model.state.model == nil)
            let account = try #require(h.model.state.account), selected = try #require(h.catalog.models.last)
            await h.model.select(selected.id, account: account)
            let stream = try await h.base.begin()
            #expect(stream.request.model == selected.id)
            await h.model.select(nil, account: account)
            #expect(h.model.state.selectedID == selected.id)
            h.model.refresh(); try await h.read().finish(.success(ChatModelCatalog(models: [])))
            try await awaitHistory { !h.model.state.loading }
            #expect(!h.base.model.state.modelAvailable)
            #expect(stream.request.model == selected.id)
            let encoded = try JSONSerialization.jsonObject(with: stream.request.encoded()) as? [String: Any]
            #expect(encoded?["model"] as? String == selected.id)
        }
    }

    @Test
    func removedSelectionBlocksSendsWithoutFallbackAndExplicitDefaultRecovers() async throws {
        try await withModels { h in
            try await h.loaded()
            let account = try #require(h.model.state.account), selected = try #require(h.catalog.models.last)
            await h.model.select(selected.id, account: account)
            h.model.refresh()
            try await h.read().finish(.success(ChatModelCatalog(models: Array(h.catalog.models.dropLast()))))
            try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.selected == selected && !h.model.state.available)
            #expect(!h.base.model.state.canSend)
            h.base.model.send(style: "标准"); await Task.yield()
            #expect(await h.base.gateway.streamCount == 0)
            await h.model.select("unknown-id", account: account)
            #expect(h.model.state.selected == selected)
            await h.model.select(nil, account: account)
            #expect(h.base.model.state.canSend)
            #expect(try await h.base.begin().request.model == nil)
        }
    }

    @Test
    func failedRefreshKeepsSelectionAndLaterSuccessUpdatesItsLabel() async throws {
        try await withModels { h in
            try await h.loaded()
            let account = try #require(h.model.state.account), selected = try #require(h.catalog.models.last)
            await h.model.select(selected.id, account: account)
            h.model.refresh(); try await h.read().finish(.failure(SessionTestError.storage))
            try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.selected == selected && h.model.state.available)
            #expect(h.model.state.notice != nil)
            h.model.refresh()
            let updated = try ChatModelOption(
                id: selected.id,
                name: "新名称",
                model: selected.model,
                source: selected.source
            )
            try await h.read().finish(.success(ChatModelCatalog(models: [updated])))
            try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.label == "新名称" && h.base.model.state.model == selected.id)
            #expect(h.model.state.notice == nil)
        }
    }

    @Test
    func lateDirectoryAndStaleSelectionCannotCrossAccountOrSameUserRevision() async throws {
        try await withModels { h in
            let oldAccount = try #require(h.model.state.account), old = try await h.read()
            try await h.login(2)
            try await h.read().finish(.success(ChatModelCatalog(models: [])))
            try await awaitHistory { !h.model.state.loading }
            await old.finish(.success(h.catalog))
            try await awaitHistory { await old.completed }
            await Task.yield()
            #expect(h.model.state.catalog?.models.isEmpty == true)
            await h.model.select(h.catalog.models.last?.id, account: oldAccount)
            #expect(h.model.state.selectedID == nil)
            try await h.login(1); try await h.loaded()
            try await h.model.select(h.catalog.models.last?.id, account: #require(h.model.state.account))
            try await h.login(1)
            #expect(h.model.state.selectedID == nil && h.base.model.state.model == nil)
            try await h.loaded()
        }
    }

    @Test
    func initialFailurePermitsServerDefaultAndLogoutClearsCachedChoices() async throws {
        try await withModels { h in
            try await h.read().finish(.failure(SessionTestError.storage))
            try await awaitHistory { !h.model.state.loading }
            #expect(h.base.model.state.canSend)
            #expect(h.model.state.label == "服务端默认" && h.model.state.notice != nil)
            h.model.refresh(); try await h.loaded()
            try await h.model.select(h.catalog.models.last?.id, account: #require(h.model.state.account))
            try await h.base.session.logout()
            await h.base.model.bindAccount(h.base.session.state)
            await h.model.bindAccount(h.base.session.state)
            #expect(h.model.state.account == nil && h.model.state.catalog == nil)
            #expect(h.base.model.state.model == nil)
        }
    }

    @Test
    func canonicallyEquivalentIDsStayDistinctThroughSelectionAndDisappearance() async throws {
        try await withModels { h in
            let first = try ChatModelOption(id: "é", name: "同名", model: "synthetic", source: .environment)
            let second = try ChatModelOption(id: "e\u{301}", name: "同名", model: "synthetic", source: .environment)
            try await h.read().finish(.success(ChatModelCatalog(models: [first, second])))
            try await awaitHistory { !h.model.state.loading }
            try await h.model.select(second.id, account: #require(h.model.state.account))
            #expect(h.base.model.state.model?.utf8.elementsEqual(second.id.utf8) == true)
            h.model.refresh(); try await h.read().finish(.success(ChatModelCatalog(models: [first])))
            try await awaitHistory { !h.model.state.loading }
            #expect(!h.model.state.available)
        }
    }
}
