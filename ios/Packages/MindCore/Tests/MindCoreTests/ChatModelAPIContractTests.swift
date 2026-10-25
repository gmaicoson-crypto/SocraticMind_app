import Foundation
@testable import MindCore
import Testing

struct ModelFixture: Decodable {
    let catalog: ChatModelCatalog
    let default_id: String
    let requests: [Choice]
    struct Choice: Decodable {
        let name: String
        let request: Payload
    }

    struct Payload: Decodable {
        let request_id: String
        let session_id: String
        let user_input: String
        let ai_style: String
        let model: String?
    }
}

func modelFixture() throws -> ModelFixture {
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0 ..< 6 {
        root.deleteLastPathComponent()
    }
    return try JSONDecoder().decode(ModelFixture.self,
                                    from: Data(contentsOf: root
                                        .appendingPathComponent("contracts/fixtures/model-selection.json")))
}

struct ChatModelAPIContractTests {
    @Test
    func directoryKeepsConfigurationIdentityAndDoesNotInferFirstAsDefault() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatModelAPI(transport: transport), fixture = try modelFixture()
        let actual = try await api.catalog(token: "models-contract")
        #expect(actual.models == fixture.catalog.models)
        #expect(Set(actual.models.map(\.model)).count == 1)
        #expect(actual.models.first?.id != fixture.default_id)
        #expect(try await api.catalog(token: "models-empty").models.isEmpty)
        let unicode = try await api.catalog(token: "models-unicode").models
        #expect(unicode.map(\.identity) == [Data("é".utf8), Data("e\u{301}".utf8)])
        #expect(unicode[0] != unicode[1])
    }

    @Test
    func defaultEnvironmentAndCustomChoicesReachStreamAndSuggestionsUnchanged() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        for item in try modelFixture().requests {
            let value = item.request
            let target = try ChatTarget(sessionID: value.session_id)
            let request = try ChatTurnRequest(
                pending: PendingChatTurn(ownerID: 1, target: target, requestID: value.request_id),
                input: value.user_input,
                style: value.ai_style,
                model: value.model
            )
            let events = EventRecorder()
            try await ChatTurnAPI(transport: transport).stream(token: "models-" + item.name, request: request) {
                await events.append($0)
            }
            #expect(await events.snapshot().contains(.done))
            let suggestions = try await ChatSuggestionsAPI(transport: transport).suggestions(
                token: "models-" + item.name, target: target, exclude: [], model: value.model
            )
            #expect(suggestions.items == ["合成模型建议🙂"])
        }
        let old = try JSONSerialization.jsonObject(with: turnRequest().encoded()) as? [String: Any]
        #expect(old?["model"] == nil)
    }

    @Test
    func malformedOrOversizedCatalogsAndInvalidRequestIDsFailClosed() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatModelAPI(transport: transport)
        for value in ["duplicate", "many", "id", "name", "model", "blank", "type", "source", "budget"] {
            await #expect(throws: (any Error).self) { try await api.catalog(token: "models-" + value) }
        }
        let original = try turnRequest()
        for value in ["", " ", String(repeating: "🙂", count: 101)] {
            #expect(throws: ChatTurnFailure.self) {
                try ChatTurnRequest(
                    pending: original.pending,
                    input: original.input,
                    style: original.style,
                    model: value
                )
            }
        }
        #expect(try ChatTurnRequest(pending: original.pending, input: original.input, style: original.style,
                                    model: String(repeating: "🙂", count: 100)).model?.unicodeScalars.count == 100)
    }

    @Test
    func authenticationFailuresAndTypedModelRejectionRetainStatusAndCode() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        for (token, status) in [("expired", 401), ("models-failure", 503)] {
            do {
                _ = try await ChatModelAPI(transport: transport).catalog(token: token)
                Issue.record("Expected rejection")
            } catch let error as HTTPFailure { #expect(error.status == status) }
        }
        do {
            try await ChatTurnAPI(transport: transport)
                .stream(token: "models-unavailable", request: turnRequest()) { _ in }
            Issue.record("Expected rejection")
        } catch let error as HTTPFailure {
            #expect(error.status == 422 && error.code == "LLM_MODEL_UNAVAILABLE")
        }
    }
}
