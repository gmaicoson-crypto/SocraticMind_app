import Foundation
@testable import MindCore
import Testing

private actor ContextEvents {
    var values: [ChatEvent] = []
    func add(_ value: ChatEvent) {
        values.append(value)
    }
}

@MainActor
struct ChatRegenerationContextTests {
    private func cases() throws -> [[String: Any]] {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        let data = try Data(contentsOf: root
            .appendingPathComponent("contracts/fixtures/chat-regeneration-contexts.json"))
        let fixture = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        return try #require(fixture["cases"] as? [[String: Any]])
    }

    private func history(_ value: [String: Any], account: HistoryAccount = HistoryAccount(userID: 1, revision: 1),
                         mutate: (inout [[String: Any]]) -> Void = { _ in }) throws -> ChatLibraryState
    {
        let request = try #require(value["request"] as? [String: Any])
        let target = try JSONDecoder().decode(ChatTarget.self, from: JSONSerialization.data(withJSONObject: request))
        var messages = try #require(value["messages"] as? [[String: Any]])
        mutate(&messages)
        var result = ChatLibraryState()
        result.account = account; result.selected = ChatConversation(target: target, title: nil)
        result.messages.items = try JSONDecoder().decode([StoredChatMessage].self,
                                                         from: JSONSerialization.data(withJSONObject: messages))
        result.messages.loaded = true
        return result
    }

    @Test
    func sharedContextsPreserveExactWireOnExistingRegenerationStream() async throws {
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        for value in try cases() {
            let candidate = try #require(ChatRegeneration.from(history(value)))
            let expected = try #require(value["request"] as? [String: Any])
            let pending = try PendingChatTurn(ownerID: 1, target: candidate.target,
                                              requestID: #require(expected["request_id"] as? String),
                                              regenerateMessageID: candidate.answerID)
            let request = try ChatTurnRequest(
                pending: pending,
                input: candidate.input,
                style: "标准",
                context: candidate.context
            )
            #expect(try JSONSerialization
                .jsonObject(with: request.encoded()) as? NSDictionary == expected as NSDictionary)
            let events = ContextEvents()
            try await ChatTurnAPI(transport: transport)
                .stream(token: "turn-context", request: request) { await events.add($0) }
            #expect(await events.values.first == .messageIDs(user: 101, ai: 103))
            #expect(await events.values.last == .done)
        }
    }

    @Test
    func contextBoundsCountScalarsAndKeepOrderedValueSnapshot() throws {
        let quote = String(repeating: "🙂", count: 200)
        #expect(try ChatRequestContext(quoteText: quote, quoteSourceID: .max).quoteText == quote)
        #expect(throws: ChatTurnFailure.self) { try ChatRequestContext(quoteText: quote + "🙂") }
        for id: Int64 in [0, -1] {
            #expect(throws: ChatTurnFailure.self) { try ChatRequestContext(quoteText: "quote", quoteSourceID: id) }
        }
        #expect(throws: ChatTurnFailure.self) { try ChatRequestContext(quoteSourceID: 1) }
        var ids = ["second", "first"]
        let context = try ChatRequestContext(attachmentIDs: ids)
        ids.removeAll()
        #expect(context.attachmentIDs == ["second", "first"])
        #expect(try ChatRequestContext(attachmentIDs: (1 ... 9).map(String.init)).attachmentIDs.count == 9)
        for invalid in [["same", "same"], [""], [String(repeating: "🙂", count: 37)], (1 ... 10).map(String.init)] {
            #expect(throws: ChatTurnFailure.self) { try ChatRequestContext(attachmentIDs: invalid) }
        }
        #expect(try ChatRequestContext(attachmentIDs: [String(repeating: "🙂", count: 36)]).attachmentIDs.count == 1)
        // Resource identity follows UTF-8, not Swift's canonical Unicode equivalence.
        #expect(try ChatRequestContext(attachmentIDs: ["é", "e\u{301}"]).attachmentIDs.count == 2)
        let pending = try turnRequest().pending
        #expect(try ChatTurnRequest(pending: pending, input: "", style: "标准", context: context).input.isEmpty)
        #expect(throws: ChatTurnFailure.self) {
            try ChatTurnRequest(
                pending: pending,
                input: "",
                style: "标准",
                context: ChatRequestContext(quoteText: "quote")
            )
        }
        for kind in [ChatKind.topicOverview, .nodeOverview] {
            let overview = try ChatRequestContext(kind: kind)
            #expect(throws: ChatTurnFailure.self) { try ChatTurnRequest(
                pending: pending,
                input: "",
                style: "标准",
                context: overview
            ) }
            #expect(throws: ChatTurnFailure.self) { try ChatRequestContext(kind: kind, attachmentIDs: ["id"]) }
            let target = try ChatTarget(sessionID: "topic", mode: .socratic, nodeKey: "递归", topicID: 7)
            let valid = try PendingChatTurn(ownerID: 1, target: target, requestID: "overview")
            #expect(try ChatTurnRequest(pending: valid, input: "", style: "标准", context: overview).input.isEmpty)
            let invalid = try PendingChatTurn(
                ownerID: 1,
                target: ChatTarget(sessionID: "topic", mode: .socratic),
                requestID: "overview"
            )
            #expect(throws: ChatTurnFailure.self) { try ChatTurnRequest(
                pending: invalid,
                input: "",
                style: "标准",
                context: overview
            ) }
        }
    }

    @Test
    func malformedQuoteSourceKindAndAnswerPairCannotSilentlyLoseContext() throws {
        let value = try #require(cases().first)
        let changes: [(String, Any)] = [("quote", true), ("quote", String(repeating: "x", count: 201)),
                                        ("quote", NSNull()), ("quote_source_id", "91"), ("quote_source_id", true), (
                                            "quote_source_id",
                                            -1
                                        ),
                                        ("kind", "unknown"), ("kind", NSNull())]
        for (key, replacement) in changes {
            let source = try history(value) { messages in
                var metadata = messages[0]["metadata"] as? [String: Any] ?? [:]
                metadata[key] = replacement; messages[0]["metadata"] = metadata
            }
            #expect(ChatRegeneration.from(source) == nil)
        }
        for id: Any in [99, "101", true, NSNull()] {
            let source = try history(value) { messages in
                var metadata = messages[1]["metadata"] as? [String: Any] ?? [:]
                metadata["user_message_id"] = id; messages[1]["metadata"] = metadata
            }
            #expect(ChatRegeneration.from(source) == nil)
        }
        let exact = try history(value) { messages in
            var metadata = messages[0]["metadata"] as? [String: Any] ?? [:]
            metadata["quote_source_id"] = Int64.max; messages[0]["metadata"] = metadata
        }
        #expect(ChatRegeneration.from(exact)?.context.quoteSourceID == .max)
        let normalized = try history(value) { messages in
            messages[0]["session_id"] = "e\u{301}"; messages[1]["session_id"] = "é"
        }
        var other = normalized
        other.selected = try ChatConversation(target: ChatTarget(sessionID: "é"), title: nil)
        #expect(ChatRegeneration.from(other) == nil)
    }

    @Test
    func attachmentSnapshotsRequireMatchingOrderRevisionCoverageAndVisibleResources() throws {
        let value = try #require(cases().first { $0["name"] as? String == "combined" })
        let changes: [(inout [[String: Any]]) -> Void] = [
            { messages in messages[0]["attachments"] = [] },
            { messages in
                messages[0]["attachments"] = Array((messages[0]["attachments"] as? [[String: Any]] ?? []).reversed()) },
            { messages in
                var meta = messages[0]["metadata"] as? [String: Any] ?? [:]
                meta.removeValue(forKey: "attachment_snapshot"); messages[0]["metadata"] = meta
            },
            { messages in
                var meta = messages[0]["metadata"] as? [String: Any] ?? [:]
                meta["attachment_snapshot"] = NSNull(); messages[0]["metadata"] = meta
            },
        ]
        for change in changes {
            #expect(try ChatRegeneration.from(history(value, mutate: change)) == nil)
        }
        for (key, replacement): (String, Any) in [("revision", 2), ("revision", "1"),
                                                  ("accepted_coverage", ["pages": 1]), ("id", "wrong")]
        {
            let source = try history(value) { messages in
                var meta = messages[0]["metadata"] as? [String: Any] ?? [:]
                var snapshots = meta["attachment_snapshot"] as? [[String: Any]] ?? []
                snapshots[0][key] = replacement; meta["attachment_snapshot"] = snapshots
                messages[0]["metadata"] = meta
            }
            #expect(ChatRegeneration.from(source) == nil)
        }
        let duplicate = try history(value) { messages in
            var meta = messages[0]["metadata"] as? [String: Any] ?? [:]
            let first = (meta["attachment_snapshot"] as? [[String: Any]])?.first ?? [:]
            meta["attachment_snapshot"] = [first, first]; messages[0]["metadata"] = meta
            let summary = (messages[0]["attachments"] as? [[String: Any]])?.first ?? [:]
            messages[0]["attachments"] = [summary, summary]
        }
        #expect(ChatRegeneration.from(duplicate) == nil)
        let derived = try history(value) { messages in
            var meta = messages[1]["metadata"] as? [String: Any] ?? [:]
            meta["attachment_derived"] = true; messages[1]["metadata"] = meta
        }
        #expect(ChatRegeneration.from(derived) != nil)
    }

    @Test
    func failedCancellationAndUnknownRejectionKeepRecoveryUntilExplicitStop() async throws {
        for (status, code, rejected) in [(400, "CHAT_QUOTE_INVALID", true), (400, nil, false),
                                         (404, "UNKNOWN", false), (500, "CHAT_QUOTE_INVALID", false), (
                                             422,
                                             "ATTACHMENT_NOT_READY",
                                             false
                                         )]
        {
            try await withTurn { h in
                try await h.login(); try await h.ready()
                let source = try history(#require(cases().first), account: #require(h.model.state.account))
                try h.model.select(#require(source.selected).target); h.model.edit("草稿")
                h.model.regenerate(history: source, style: "标准")
                let stream = try await nextTurn { await h.gateway.popStream() }
                stream.continuation.finish(throwing: HTTPFailure(status: status, code: code,
                                                                 userMessage: "unavailable", retryable: false))
                let unresolved = rejected ? try await h.cancel() : try await h.status()
                await unresolved.finish(.failure(HTTPFailure(
                    status: 503,
                    code: nil,
                    userMessage: "offline",
                    retryable: true
                )))
                try await awaitHistory { h.model.state.phase == .unresolved }
                #expect(try await h.journal.read(ownerID: 1) == stream.request.pending)
                #expect(h.model.state.draft == "草稿")
                #expect(h.model.state.receipt == nil)
                #expect(await h.gateway.streamCount == 0)
                if !rejected {
                    #expect(await h.gateway.popCancel() == nil)
                }
                h.model.stop()
                try await (h.cancel()).finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
                try await awaitHistory { h.model.state.editable }
                #expect(try await h.journal.read(ownerID: 1) == nil)
            }
        }
    }

    @Test
    func allSharedContextsReuseSaveSendAndReceiptHandoffWhileRetainingDraft() async throws {
        for value in try cases() {
            try await withTurn { h in
                try await h.login(); try await h.ready()
                let source = try history(value, account: #require(h.model.state.account))
                try h.model.select(#require(source.selected).target); h.model.edit("尚未发送的草稿")
                h.model.regenerate(history: source, style: "标准")
                let stream = try await nextTurn { await h.gateway.popStream() }
                var expected = try #require(value["request"] as? [String: Any])
                expected["request_id"] = "turn-contract-id"
                #expect(try JSONSerialization
                    .jsonObject(with: stream.request.encoded()) as? NSDictionary == expected as NSDictionary)
                #expect(stream.saved == stream.request.pending)
                stream.continuation.yield(.messageIDs(user: 101, ai: 103)); stream.continuation.finish()
                try await h.status().finish(.success(RemoteChatTurn(
                    status: .complete,
                    ids: ChatMessageIDs(user: 101, ai: 103)
                )))
                let read = try await nextTurn { await h.gateway.popMessages() }
                let messages = try history(value) { $0[1]["id"] = 103 }.messages.items
                await read.finish(.success(messages))
                try await awaitHistory { h.model.state.editable }
                #expect(h.model.state.receipt?.replacedMessageID == 102)
                #expect(h.model.state.draft == "尚未发送的草稿")
                #expect(try await h.journal.read(ownerID: 1) == nil)
            }
        }
    }

    @Test
    func typedUnavailableContextWaitsForCancellationAndUnknownErrorsKeepRecovery() async throws {
        for (status, code) in [(400, "CHAT_QUOTE_INVALID"), (404, "ATTACHMENT_NOT_FOUND"),
                               (422, "ATTACHMENT_SCOPE_MISMATCH")]
        {
            try await withTurn { h in
                try await h.login(); try await h.ready()
                let source = try history(#require(cases().first), account: #require(h.model.state.account))
                try h.model.select(#require(source.selected).target); h.model.edit("草稿")
                h.model.regenerate(history: source, style: "标准")
                let stream = try await nextTurn { await h.gateway.popStream() }
                stream.continuation.finish(throwing: HTTPFailure(
                    status: status,
                    code: code,
                    userMessage: "gone",
                    retryable: false
                ))
                let stop = try await h.cancel()
                #expect(try await h.journal.read(ownerID: 1) == stream.request.pending)
                #expect(!h.model.state.editable)
                await stop.finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
                try await awaitHistory { h.model.state.editable }
                #expect(try await h.journal.read(ownerID: 1) == nil)
                #expect(h.model.state.draft == "草稿")
                #expect(h.model.state.receipt?.replacedMessageID == nil)
                #expect(await h.gateway.statusCount == 0)
            }
        }
        for (status, code) in [(400, nil), (404, "UNKNOWN"), (500, "CHAT_QUOTE_INVALID")] {
            #expect(!ChatRegeneration.rejected(HTTPFailure(
                status: status,
                code: code,
                userMessage: "unknown",
                retryable: false
            )))
        }
    }
}
