import Foundation
@testable import MindCore
import Testing

struct TurnFixture: Decodable {
    let request: Request
    let messages: [StoredChatMessage]
    let invalid_status: [Invalid]
    let cancel_cases: [Cancel]
    struct Request: Decodable {
        let request_id: String; let session_id: String; let user_input: String; let ai_style: String
    }

    struct Invalid: Decodable { let id: String }
    struct Cancel: Decodable { let id: String; let valid: Bool }
}

func turnFixture() throws -> TurnFixture {
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0 ..< 6 {
        root.deleteLastPathComponent()
    }
    let data = try Data(contentsOf: root.appendingPathComponent("contracts/fixtures/chat-turns.json"))
    return try JSONDecoder().decode(TurnFixture.self, from: data)
}

func turnRequest() throws -> ChatTurnRequest {
    let value = try turnFixture().request
    return try ChatTurnRequest(
        pending: PendingChatTurn(
            ownerID: 1,
            target: ChatTarget(sessionID: value.session_id),
            requestID: value.request_id
        ),
        input: value.user_input, style: value.ai_style
    )
}

private actor TurnEvents {
    var values: [ChatEvent] = []
    func add(_ value: ChatEvent) {
        values.append(value)
    }
}

struct ChatTurnAPIContractTests {
    @Test
    func liveBufferRejectsIdentityChangeTerminalReversalAndExcessiveText() throws {
        var buffer = ChatTurnBuffer()
        try buffer.accept(.messageIDs(user: 1, ai: 2))
        try buffer.accept(.text("原文"))
        #expect(throws: ChatTurnFailure.self) { try buffer.accept(.messageIDs(user: 3, ai: 4)) }
        try buffer.accept(.requestState("complete"))
        #expect(throws: ChatTurnFailure.self) { try buffer.accept(.requestState("generating")) }
        #expect(throws: ChatTurnFailure.self) { try buffer.accept(.text("迟到")) }
        #expect(buffer.content == "原文")
        var bounded = ChatTurnBuffer()
        try bounded.accept(.text(String(repeating: "x", count: 512 * 1024)))
        #expect(throws: ChatTurnFailure.self) { try bounded.accept(.text("🙂")) }
        #expect(bounded.content.utf8.count == 512 * 1024)
        #expect(throws: ChatTurnFailure.self) { try ChatTarget(sessionID: " padded ") }
    }

    @Test
    func wirePreservesInputAndStableIDsThenReadsExactAuthoritativeMessages() async throws {
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        let api = ChatTurnAPI(transport: transport), request = try turnRequest()
        let events = TurnEvents()
        try await api.stream(token: "turn-contract", request: request) { await events.add($0) }
        let values = await events.values
        #expect(values.first == .messageIDs(user: 101, ai: 102))
        #expect(values.last == .done)
        #expect(values.compactMap {
            if case let .text(value) = $0 {
                value
            } else {
                nil
            }
        }.joined() == "你好，世界🙂")
        for status in [ChatTurnStatus.generating, .complete, .failed, .interrupted] {
            #expect(try await api.status(token: "turn-" + status.rawValue, pending: request.pending).status == status)
        }
        let messages = try await api.messages(token: "turn-contract", pending: request.pending,
                                              ids: ChatMessageIDs(user: 101, ai: 102))
        #expect(try messages == (turnFixture().messages))
        #expect(try await ChatHistoryAPI(transport: transport).message(
            token: "turn-neighbour",
            sessionID: request.pending.target.sessionID,
            id: 102
        ) == nil)
    }

    @Test
    func statusRejectsMismatchesAndPreservesNotFoundDeletedAndUnauthorized() async throws {
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        let api = ChatTurnAPI(transport: transport), pending = try turnRequest().pending
        for item in try turnFixture().invalid_status {
            do {
                _ = try await api.status(token: "turn-" + item.id, pending: pending)
                Issue.record("Accepted invalid status: \(item.id)")
            } catch is ChatTurnFailure {} catch is DecodingError {}
        }
        for (token, code) in [("expired", 401), ("turn-missing", 404), ("turn-deleted", 409)] {
            do {
                _ = try await api.status(token: token, pending: pending)
                Issue.record("Expected HTTP failure")
            } catch let error as HTTPFailure { #expect(error.status == code) }
        }
    }

    @Test
    func cancelSupportsTombstoneAndCompletionRaceButRejectsUnconfirmedResponses() async throws {
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        let api = ChatTurnAPI(transport: transport), pending = try turnRequest().pending
        for item in try turnFixture().cancel_cases {
            do {
                let result = try await api.cancel(token: "turn-" + item.id, pending: pending)
                #expect(item.valid, "Accepted invalid cancellation: \(item.id)")
                if item.id == "tombstone" {
                    #expect(result.ids == nil)
                }
                if item.id == "complete" {
                    #expect(result.status == .complete)
                }
            } catch { #expect(!item.valid, "Rejected valid cancellation: \(item.id)") }
        }
    }

    @Test
    func scalarInputLimitAndPathSafeRequestIDs() throws {
        let pending = try turnRequest().pending
        #expect(try ChatTurnRequest(pending: pending, input: String(repeating: "🙂", count: 5000), style: "标准")
            .input.unicodeScalars.count == 5000)
        #expect(throws: ChatTurnFailure.self) {
            try ChatTurnRequest(pending: pending, input: String(repeating: "🙂", count: 5001), style: "标准")
        }
        #expect(throws: ChatTurnFailure.self) { try ChatTurnRequest(pending: pending, input: " \n\t", style: "标准") }
        for value in ["", "../x", "x?x", "x#x", "x%2f", "x\\x", "中", String(repeating: "a", count: 101)] {
            #expect(throws: ChatTurnFailure.self) { try PendingChatTurn(
                ownerID: 1,
                target: pending.target,
                requestID: value
            ) }
        }
    }
}
