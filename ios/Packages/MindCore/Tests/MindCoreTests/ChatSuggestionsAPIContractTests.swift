import Foundation
@testable import MindCore
import Testing

struct SuggestionsFixture: Decodable {
    let target: Target
    let exclude: [String]
    let result: ChatSuggestions
    let fallback: ChatSuggestions
    let defaults: [String: [String]]
    struct Target: Decodable { let session_id: String }
}

func suggestionFixture() throws -> SuggestionsFixture {
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0 ..< 6 {
        root.deleteLastPathComponent()
    }
    return try JSONDecoder().decode(SuggestionsFixture.self,
                                    from: Data(contentsOf: root
                                        .appendingPathComponent("contracts/fixtures/chat-suggestions.json")))
}

struct ChatSuggestionsAPIContractTests {
    @Test
    func normalTopicEmptyAndFallbackKeepContextAndRepeatedUnicodeExclusions() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatSuggestionsAPI(transport: transport), data = try suggestionFixture()
        let target = try ChatTarget(sessionID: data.target.session_id)
        #expect(try await api.suggestions(
            token: "suggestions-contract",
            target: target,
            exclude: data.exclude,
            model: nil
        ) == data.result)
        #expect(try await api.suggestions(
            token: "suggestions-fallback",
            target: target,
            exclude: data.exclude,
            model: nil
        ) == data.fallback)
        #expect(try await api.suggestions(token: "suggestions-empty", target: target, exclude: data.exclude, model: nil)
            .items.isEmpty)
        let topic = try ChatTarget(sessionID: data.target.session_id, mode: .socratic, nodeKey: "节点 /+🙂", topicID: 7)
        #expect(try await api.suggestions(
            token: "suggestions-topic",
            target: topic,
            exclude: data.exclude,
            model: "model /+🙂"
        ).source == .ai)
    }

    @Test
    func malformedResponsesAndUnboundedInputsFailClosed() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatSuggestionsAPI(transport: transport), data = try suggestionFixture()
        let target = try ChatTarget(sessionID: data.target.session_id)
        for value in ["source", "duplicate", "blank", "type", "many", "long", "budget"] {
            await #expect(throws: (any Error).self) {
                try await api.suggestions(
                    token: "suggestions-" + value,
                    target: target,
                    exclude: data.exclude,
                    model: nil
                )
            }
        }
        for invalid in [(0 ..< 25).map { "x\($0)" }, [" "], [String(repeating: "🙂", count: 5001)]] {
            await #expect(throws: ChatTurnFailure.self) {
                try await api.suggestions(token: "suggestions-contract", target: target, exclude: invalid, model: nil)
            }
        }
        await #expect(throws: ChatTurnFailure.self) {
            try await api.suggestions(token: "suggestions-contract", target: target, exclude: data.exclude, model: " ")
        }
    }

    @Test
    func authorizationConfigurationAndServiceErrorsStayExplicit() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatSuggestionsAPI(transport: transport), data = try suggestionFixture()
        let target = try ChatTarget(sessionID: data.target.session_id)
        for (token, status) in [("expired", 401), ("suggestions-configuration", 422), (
            "suggestions-unavailable",
            503
        )] {
            do {
                _ = try await api.suggestions(token: token, target: target, exclude: data.exclude, model: nil); Issue
                    .record("Expected failure")
            } catch let error as HTTPFailure { #expect(error.status == status) }
        }
    }
}
