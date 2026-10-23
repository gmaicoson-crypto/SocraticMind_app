import Foundation
@testable import MindCore
import Testing

private struct ActionsFixture: Decodable {
    let batch_ids: [String]
    let batch_titles: [ChatTitle]
    let session_id: String
    let renamed: ChatTitle
    let rename: Rename
    let message_ids: [Int64]
    let invalid_titles: [Invalid]
    struct Rename: Decodable { let title: String }
    struct Invalid: Decodable { let id: String }
}

private func actionsFixture() throws -> ActionsFixture {
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0 ..< 6 {
        root.deleteLastPathComponent()
    }
    return try JSONDecoder().decode(
        ActionsFixture.self,
        from: Data(contentsOf: root.appendingPathComponent("contracts/fixtures/chat-actions.json"))
    )
}

struct ChatActionsAPIContractTests {
    @Test
    func bulkTitleReadsEncodeRepeatedIDsAndValidateReturnedSubsets() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatActionsAPI(transport: transport), data = try actionsFixture()
        #expect(try await api.titles(token: "actions-batch", sessionIDs: data.batch_ids) == data.batch_titles)
        for value in ["duplicate", "unrequested"] {
            await #expect(throws: HistoryContractFailure.self) {
                try await api.titles(token: "actions-batch-" + value, sessionIDs: data.batch_ids)
            }
        }
        for ids in [[], ["x", "x"], [""], (1 ... 101).map { "s\($0)" }] {
            await #expect(throws: (any Error).self) { try await api.titles(token: "actions-batch", sessionIDs: ids) }
        }
    }

    @Test
    func titleRenameAndDeletesPreserveOpaqueIdentityAndExactBody() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatActionsAPI(transport: transport), data = try actionsFixture()
        #expect(try await api.title(token: "actions-contract", sessionID: data.session_id) == data.renamed)
        #expect(try await api.title(token: "actions-empty", sessionID: data.session_id) == nil)
        #expect(try await api
            .rename(token: "actions-contract", sessionID: data.session_id, title: data.rename.title) == data.renamed)
        #expect(try await api.deleteSession(token: "actions-contract", sessionID: data.session_id) == 2)
        #expect(try await api.deleteMessages(token: "actions-contract", ids: data.message_ids) == 2)
    }

    @Test
    func invalidTitlesCannotBecomeSuccessfulReadOrRename() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatActionsAPI(transport: transport), data = try actionsFixture()
        for item in data.invalid_titles {
            let token = "actions-" + item.id
            await #expect(throws: (any Error).self) { try await api.title(token: token, sessionID: data.session_id) }
            await #expect(throws: (any Error).self) { try await api.rename(
                token: token,
                sessionID: data.session_id,
                title: data.rename.title
            ) }
        }
        await #expect(throws: HistoryContractFailure.self) { try await api.title(
            token: "actions-duplicate",
            sessionID: data.session_id
        ) }
    }

    @Test
    func invalidCountsAndLocalMutationInputsFailClosed() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatActionsAPI(transport: transport), data = try actionsFixture()
        for value in ["negative", "excessive", "string", "boolean"] {
            await #expect(throws: (any Error).self) { try await api.deleteMessages(
                token: "actions-" + value,
                ids: data.message_ids
            ) }
        }
        for ids: [Int64] in [[], [0], [1, 1], Array(1 ... 101)] {
            await #expect(throws: ChatTurnFailure.self) { try await api.deleteMessages(
                token: "actions-contract",
                ids: ids
            ) }
        }
        for title in [" ", String(repeating: "🙂", count: 41)] {
            await #expect(throws: ChatTurnFailure.self) { try await api.rename(
                token: "actions-contract",
                sessionID: data.session_id,
                title: title
            ) }
        }
        await #expect(throws: ChatTurnFailure.self) { try await api.deleteSession(
            token: "actions-contract",
            sessionID: " padded "
        ) }
    }

    @Test
    func httpFailuresStayVisible() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatActionsAPI(transport: transport), data = try actionsFixture()
        for (token, status) in [
            ("expired", 401),
            ("actions-missing", 404),
            ("actions-unsupported", 405),
            ("actions-unavailable", 503),
        ] {
            let calls: [() async throws -> Void] = [
                { _ = try await api.title(token: token, sessionID: data.session_id) },
                { _ = try await api.rename(token: token, sessionID: data.session_id, title: data.rename.title) },
                { _ = try await api.deleteSession(token: token, sessionID: data.session_id) },
                { _ = try await api.deleteMessages(token: token, ids: data.message_ids) },
            ]
            for call in calls {
                do { try await call(); Issue.record("Expected HTTP failure") }
                catch let error as HTTPFailure { #expect(error.status == status) }
            }
        }
    }
}
