import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatTurnModelTests {
    @Test
    func failureAfterDeletingJournalStillHandsMessagesToHistory() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); try await h.begin().continuation.finish()
            await h.journal.failures(afterClear: true)
            try await h.resolve(h.status())
            #expect(h.model.state.phase == .storageFailed)
            #expect(await h.journal.records[1] == nil)
            let receipt = try #require(h.model.state.receipt)
            #expect(receipt.messages.last?.content == "你好，世界🙂")
            h.model.verify()
            try await awaitHistory { h.model.state.editable }
            #expect(h.model.state.receipt == receipt)
            #expect(await h.gateway.statusCount == 0)
            h.model.acknowledge(receipt)
            #expect(h.model.state.receipt == nil)
        }
    }

    @Test
    func completionSurvivesSelectionUntilHistoryAcknowledges() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); try await h.begin().continuation.finish()
            try await h.resolve(h.status())
            try h.model.select(ChatTarget(sessionID: "next-session")); h.model.edit("next question")
            h.model.send(style: "标准")
            #expect(h.model.state.receipt != nil)
            #expect(await h.gateway.streamCount == 0)
            let receipt = try #require(h.model.state.receipt)
            let different = try PendingChatTurn(ownerID: 1, target: receipt.pending.target, requestID: "different")
            h.model.acknowledge(ChatTurnReceipt(pending: different, status: receipt.status, messages: receipt.messages))
            #expect(!h.model.state.canSend)
            h.model.acknowledge(receipt)
            #expect(h.model.state.receipt == nil && h.model.state.canSend)
        }
    }

    @Test
    func saveBeforePOSTSuppressDoubleSendAndDONERequiresAuthoritativeStatus() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            let stream = try await h.begin()
            #expect(stream.saved == stream.request.pending)
            h.model.send(style: "标准"); h.model.edit("must not replace submitted input")
            #expect(await h.gateway.streamCount == 0)
            stream.continuation.yield(.messageIDs(user: 101, ai: 102))
            stream.continuation.yield(.text("provisional"))
            stream.continuation.yield(.done); stream.continuation.finish()
            let status = try await h.status()
            #expect(h.model.state.phase == .verifying && h.model.state.receipt == nil)
            #expect(await h.journal.records[1] != nil)
            try await h.resolve(status)
            #expect(h.model.state.receipt?.messages.last?.content == "你好，世界🙂")
            #expect(h.model.state.partial.isEmpty)
            #expect(await h.journal.records[1] == nil)
        }
    }

    @Test
    func disconnectAnd404RemainUnresolvedAndRetryIsGETOnly() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            let stream = try await h.begin()
            stream.continuation.yield(.text("partial")); stream.continuation.finish(throwing: SessionTestError.offline)
            try await h.status().finish(.failure(HTTPFailure(status: 404, code: "CHAT_REQUEST_NOT_FOUND",
                                                             userMessage: "missing", retryable: nil)))
            try await awaitHistory { h.model.state.phase == .unresolved }
            #expect(h.model.state.partial == "partial")
            h.model.send(style: "标准")
            #expect(await h.gateway.streamCount == 0)
            h.model.verify(); try await h.resolve(h.status())
            #expect(await h.journal.records[1] == nil)
        }
    }

    @Test
    func cancelRacingCompletionDisplaysCompletedResponse() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); _ = try await h.begin()
            h.model.stop()
            #expect(h.model.state.phase == .stopping)
            try await h.resolve(h.cancel())
            #expect(h.model.state.receipt?.status == .complete)
            #expect(await h.gateway.statusCount == 0)
        }
    }

    @Test
    func failedCancelRetriesDurableTombstoneWithoutInventingMessages() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); _ = try await h.begin(); h.model.stop()
            try await h.cancel().finish(.failure(SessionTestError.offline))
            try await awaitHistory { h.model.state.phase == .unresolved }
            #expect(await h.journal.records[1] != nil)
            h.model.stop()
            try await h.cancel().finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
            try await awaitHistory { h.model.state.editable }
            #expect(h.model.state.receipt?.status == .interrupted)
            #expect(h.model.state.receipt?.messages.isEmpty == true)
            #expect(await h.gateway.messageCount == 0)
        }
    }

    @Test
    func controllerReopensIDsAndFinitePollingNeverReposts() async throws {
        let journal = MemoryTurnJournal()
        try await journal.save(turnRequest().pending)
        try await withTurn(journal) { h in
            try await h.login()
            try await h.status().finish(.success(RemoteChatTurn(
                status: .generating,
                ids: ChatMessageIDs(user: 101, ai: 102)
            )))
            try await awaitHistory { h.model.state.phase == .unresolved }
            #expect(try h.model.state.target == (turnRequest().pending.target))
            #expect(h.model.state.submitted.isEmpty)
            #expect(await h.gateway.streamCount == 0)
            h.model.verify(); try await h.resolve(h.status())
            #expect(await journal.records[1] == nil)
        }
    }

    @Test(arguments: [false, true])
    func failedSaveNeverSendsAndRetainsDraft(after: Bool) async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            await h.journal.failures(save: !after, after: after)
            h.model.send(style: "标准")
            try await awaitHistory { h.model.state.phase == .storageFailed }
            #expect(try h.model.state.draft == (turnRequest().input))
            #expect(await h.gateway.streamCount == 0)
            await h.journal.failures()
            h.model.verify()
            if after {
                try await h.status().finish(.failure(HTTPFailure(
                    status: 404,
                    code: nil,
                    userMessage: "unknown",
                    retryable: nil
                )))
                try await awaitHistory { h.model.state.phase == .unresolved }
            } else {
                try await awaitHistory { h.model.state.editable }
            }
        }
    }

    @Test
    func journalReadAndClearFailuresBlockNewSendsUntilRecovery() async throws {
        try await withTurn { h in
            await h.journal.failures(read: true)
            try await h.login()
            try await awaitHistory { h.model.state.phase == .storageFailed }
            await h.journal.failures(); h.model.verify(); try await h.ready()
            try await h.begin().continuation.finish()
            await h.journal.failures(clear: true)
            try await h.resolve(h.status())
            #expect(h.model.state.phase == .storageFailed)
            #expect(await h.journal.records[1] != nil)
            await h.journal.failures(); h.model.verify(); try await h.resolve(h.status())
            #expect(await h.journal.records[1] == nil)
        }
    }

    @Test(arguments: [false, true])
    func oldNoncooperativeStatusOr401CannotLeakToNewAccount(unauthorized: Bool) async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); try await h.begin().continuation.finish()
            let old = try await h.status()
            h.model.clear(); try await h.session.logout(); try await h.login(2)
            try await awaitHistory { h.model.state.editable }
            if unauthorized {
                await old.finish(.failure(HTTPFailure(status: 401, code: nil, userMessage: "expired", retryable: nil)))
            } else {
                try await old.finish(.success(RemoteChatTurn(
                    status: .complete,
                    ids: ChatMessageIDs(user: 101, ai: 102)
                )))
            }
            try await awaitHistory { await old.completed }
            #expect(await HistoryAccount.from(h.session.state)?.userID == 2)
            #expect(h.model.state.account?.userID == 2 && h.model.state.receipt == nil)
            #expect(await h.gateway.messageCount == 0)
            #expect(await h.journal.records[1] != nil)
        }
    }

    @Test(arguments: [false, true])
    func current401ClearsStateAndDeletedRequestIsTerminalWithoutPOST(deleted: Bool) async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); try await h.begin().continuation.finish()
            try await h.status().finish(.failure(HTTPFailure(status: deleted ? 409 : 401,
                                                             code: deleted ? "CHAT_REQUEST_DELETED" : nil,
                                                             userMessage: "changed", retryable: nil)))
            if deleted {
                try await awaitHistory { h.model.state.editable }
                #expect(h.model.state.receipt?.messages.isEmpty == true)
                #expect(await h.journal.records[1] == nil)
            } else {
                try await awaitHistory { h.model.state.account == nil }
                #expect(await h.session.state == .signedOut(expired: true))
                #expect(await h.journal.records[1] != nil)
            }
        }
    }

    @Test
    func lateVerificationCannotOverrideConfirmedStop() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); try await h.begin().continuation.finish()
            let old = try await h.status()
            h.model.stop()
            try await h.cancel().finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
            try await awaitHistory { h.model.state.editable }
            try await old.finish(.success(RemoteChatTurn(status: .complete, ids: ChatMessageIDs(user: 101, ai: 102))))
            try await awaitHistory { await old.completed }
            #expect(h.model.state.receipt?.status == .interrupted)
            #expect(await h.gateway.messageCount == 0)
        }
    }
}
