import Foundation
@testable import MindCore
import Testing

struct FeedbackFixture: Decodable {
    let reported_usage: ChatJSONValue
    let zero_usage: ChatJSONValue
    let usage_cases: [UsageCase]
    let errors: [ErrorCase]
    struct UsageCase: Decodable { let name: String; let input: ChatJSONValue; let expected: ChatJSONValue }
    struct ErrorCase: Decodable { let kind: String; let code: String; let message: String; let retryable: Bool }
}

func feedbackFixture() throws -> FeedbackFixture {
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0 ..< 6 {
        root.deleteLastPathComponent()
    }
    return try JSONDecoder().decode(
        FeedbackFixture.self,
        from: Data(contentsOf: root.appendingPathComponent("contracts/fixtures/chat-feedback.json"))
    )
}

func feedbackValue(_ code: String, status: ChatTurnStatus = .failed) throws -> ChatAnswerFeedback {
    try ChatAnswerFeedback.decode(
        ["error_code": .string(code), "usage": feedbackFixture().reported_usage],
        status: status
    )
}

struct ChatFeedbackContractTests {
    private struct WireFixture: Decodable {
        let cases: [Case]
        struct Case: Decodable { let name: String; let valid_state: Bool; let expected_total: Int64? }
    }

    private func wireCases() throws -> [WireFixture.Case] {
        let url = fixtureURL().deletingLastPathComponent().appendingPathComponent("chat-feedback-wire.json")
        return try JSONDecoder().decode(WireFixture.self, from: Data(contentsOf: url)).cases
    }

    @Test
    func rawDecimalAndUnrepresentableUsageNeverBlockTerminalStatusHistoryOrCancel() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatTurnAPI(transport: transport)
        for item in try wireCases() where item.valid_state {
            let token = "turn-feedback-wire-\(item.name)"
            let pending = try turnRequest().pending
            let state = try await api.status(token: token, pending: pending)
            #expect(state.status == .interrupted && state.feedback?.failure?.code == "AI_TIMEOUT")
            #expect(state.feedback?.usage?.total == item.expected_total, Comment(rawValue: item.name))
            let cancel = try await api.cancel(token: token, pending: pending)
            #expect(cancel.status == state.status && cancel.feedback?.usage?.total == item.expected_total)
            let messages = try await api.messages(token: token, pending: pending, ids: #require(state.ids))
            let answer = try #require(messages.last)
            let feedback = try #require(ChatAnswerFeedback.from(answer))
            #expect(feedback.usage?.total == item.expected_total && feedback.failure?.code == "AI_TIMEOUT")
        }
    }

    @Test
    func invalidOptionalFeedbackCannotWeakenCoreIdentityStatusOrMessageIDs() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        for item in try wireCases() where !item.valid_state {
            await #expect(throws: (any Error).self) {
                try await ChatTurnAPI(transport: transport).status(
                    token: "turn-feedback-wire-\(item.name)",
                    pending: turnRequest().pending
                )
            }
        }
    }

    @Test
    func sharedUsageCasesStayExactOrUnknownAcrossStatusHistoryAndCancel() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatTurnAPI(transport: transport)
        for item in try feedbackFixture().usage_cases {
            let token = "turn-feedback-usage-\(item.name)"
            let pending = try turnRequest().pending
            let state = try await api.status(token: token, pending: pending)
            let expected = ReportedTokenUsage.decode(item.expected)
            #expect(state.feedback?.usage == expected, Comment(rawValue: item.name))
            let cancel = try await api.cancel(token: token, pending: pending)
            #expect(cancel.feedback?.usage == expected)
            let messages = try await api.messages(token: token, pending: pending, ids: #require(state.ids))
            #expect(try ChatAnswerFeedback.from(#require(messages.last))?.usage == expected)
            #expect(state.feedback?.failure == nil)
            #expect((item.expected == .null) == state.feedback?.usageSummary.contains("未知"))
        }
    }

    @Test
    func sharedErrorsUseLocalSafeDescriptionsAndRetainAnswerReport() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatTurnAPI(transport: transport)
        for item in try feedbackFixture().errors {
            let token = "turn-feedback-error-\(item.kind)"
            let pending = try turnRequest().pending
            let state = try await api.status(token: token, pending: pending)
            let feedback = try #require(state.feedback)
            #expect(feedback.failure?.code == item.code && feedback.failure?.message == item.message)
            #expect(feedback.failure?.retryable == item.retryable && feedback.usage?.total == 59)
            let messages = try await api.messages(token: token, pending: pending, ids: #require(state.ids))
            #expect(try ChatAnswerFeedback.from(#require(messages.last)) == feedback)
            #expect(!String(describing: feedback).contains("synthetic-private-key"))
        }
    }

    @Test
    func legacyResponsesAndUnknownCodesNeverEchoProviderText() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let state = try await ChatTurnAPI(transport: transport).status(
            token: "turn-contract",
            pending: turnRequest().pending
        )
        #expect(state.feedback?.usage == nil && state.feedback?.failure == nil)
        let unknown = try feedbackValue(String(repeating: "private-key-", count: 10000))
        #expect(unknown.failure?.code == "AI_STREAM_ERROR")
        #expect(!String(describing: unknown).contains("private-key"))
        #expect(try feedbackValue("AI_QUOTA_EXCEEDED", status: .complete).failure == nil)
        #expect(try feedbackValue("AI_TIMEOUT", status: .generating).failure == nil)
    }

    @Test
    func historyOnlyPresentsStableAIAnswersAndDoesNotMistakeMissingForZero() throws {
        let messages = try turnFixture().messages
        #expect(ChatAnswerFeedback.from(messages[0]) == nil)
        let input = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL())) as? [String: Any])
        let originals = try #require(input["messages"] as? [[String: Any]])
        for status in ["streaming", "generating", "superseded", "failed", "interrupted"] {
            var answer = originals[1]
            answer["metadata"] = ["status": status]
            let message = try JSONDecoder().decode(
                StoredChatMessage.self,
                from: JSONSerialization.data(withJSONObject: answer)
            )
            if ["failed", "interrupted"].contains(status) {
                #expect(ChatAnswerFeedback.from(message)?.failure?.code == "AI_STREAM_ERROR")
            } else {
                #expect(ChatAnswerFeedback.from(message) == nil)
            }
        }
        let zero = try ChatAnswerFeedback(usage: ReportedTokenUsage.decode(feedbackFixture().zero_usage), failure: nil)
        #expect(zero.usageSummary.contains("合计 0") && !zero.usageSummary.contains("未知"))
        #expect(ChatAnswerFeedback.from(messages[1])?.usageSummary.contains("未知") == true)
    }

    private func fixtureURL() -> URL {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        return root.appendingPathComponent("contracts/fixtures/chat-turns.json")
    }
}
