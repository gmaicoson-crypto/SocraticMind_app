import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatModelSendTests {
    private let rejected = HTTPFailure(status: 422, code: "LLM_MODEL_UNAVAILABLE",
                                       userMessage: "synthetic rejection", retryable: false)

    @Test
    func typedRejectionWaitsForDurableStopAndPreservesInputAfterFailedCancellationRetry() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            try h.model.setModelSelection(account: #require(h.model.state.account), model: "env:first", available: true)
            let stream = try await h.begin()
            stream.continuation.finish(throwing: rejected)
            let first = try await h.cancel()
            #expect(try await h.journal.read(ownerID: 1) == stream.request.pending)
            #expect(h.model.state.draft.isEmpty)
            await first.finish(.failure(SessionTestError.storage))
            try await awaitHistory { h.model.state.phase == .unresolved }
            #expect(h.model.state.submitted == stream.request.input)
            h.model.stop()
            try await h.cancel().finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
            try await awaitHistory { h.model.state.editable }
            #expect(h.model.state.draft == stream.request.input)
            #expect(h.model.state.notice?.contains("模型不可用") == true)
            #expect(try await h.journal.read(ownerID: 1) == nil)
            #expect(await h.gateway.streamCount == 0)
            #expect(await h.gateway.statusCount == 0)
        }
    }

    @Test
    func confirmedModelRejectionKeepsDraftWhenJournalClearFailsBeforeOrAfterDeletion() async throws {
        for after in [false, true] {
            try await withTurn { h in
                try await h.login(); try await h.ready()
                let stream = try await h.begin()
                stream.continuation.finish(throwing: rejected)
                await h.journal.failures(clear: !after, afterClear: after)
                try await h.cancel().finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
                try await awaitHistory { h.model.state.phase == .storageFailed }
                #expect(h.model.state.draft == stream.request.input && !h.model.state.canSend)
                await h.journal.failures()
                h.model.verify()
                if !after {
                    try await h.status().finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
                }
                try await awaitHistory { h.model.state.editable }
                #expect(h.model.state.draft == stream.request.input)
                #expect(try await h.journal.read(ownerID: 1) == nil)
                #expect(await h.gateway.streamCount == 0)
            }
        }
    }

    @Test
    func genericValidationOrWrongStatusErrorsStillQueryAndNeverAssumePreflightRejection() async throws {
        for error in [HTTPFailure(status: 422, code: "VALIDATION_ERROR", userMessage: "invalid", retryable: false),
                      HTTPFailure(
                          status: 500,
                          code: "LLM_MODEL_UNAVAILABLE",
                          userMessage: "server failure",
                          retryable: false
                      )]
        {
            try await withTurn { h in
                try await h.login(); try await h.ready()
                let stream = try await h.begin()
                stream.continuation.finish(throwing: error)
                let status = try await h.status()
                #expect(await h.gateway.popCancel() == nil)
                await status.finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
                try await awaitHistory { h.model.state.editable }
                #expect(h.model.state.draft.isEmpty)
            }
        }
    }

    @Test
    func regenerationUsesCurrentChoiceAndRejectionRetainsOldAnswerAndSeparateDraft() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); h.model.edit("保留草稿🙂")
            let account = try #require(h.model.state.account)
            var source = ChatLibraryState()
            source.account = account
            source.selected = try ChatConversation(target: turnRequest().pending.target, title: nil)
            source.messages.items = try turnFixture().messages; source.messages.loaded = true
            h.model.setModelSelection(account: account, model: "env:second", available: true)
            h.model.regenerate(history: source, style: "标准")
            let stream = try await nextTurn { await h.gateway.popStream() }
            #expect(stream.request.model == "env:second")
            #expect(try stream.request.input == turnRequest().input)
            #expect(stream.request.pending.regenerateMessageID == 102)
            stream.continuation.finish(throwing: rejected)
            try await h.cancel().finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
            try await awaitHistory { h.model.state.editable }
            #expect(h.model.state.draft == "保留草稿🙂")
            let receipt = try #require(h.model.state.receipt)
            #expect(receipt.replacedMessageID == nil)
            #expect(source.messages.items.filter(receipt.retains) == source.messages.items)
        }
    }

    @Test
    func changingChoiceDiscardsStaleSuggestionConfirmationAndSendsTheConfirmedModel() async throws {
        try await withSuggestions { h in
            h.model.setModel("é"); h.model.setActive(true)
            let old = try await h.gateway.next()
            #expect(old.model == "é")
            try await old.succeed(["旧建议"])
            try await awaitHistory { !h.model.state.loading }
            h.base.turn.edit("手写草稿")
            try await h.model.choose("旧建议", context: #require(h.model.state.context), style: "标准")
            #expect(h.model.state.choice != nil)
            h.model.setModel("e\u{301}")
            h.model.confirmChoice(style: "标准")
            #expect(h.model.state.choice == nil)
            #expect(await h.base.turnGateway.streamCount == 0)
            let current = try await h.gateway.next()
            #expect(current.model?.utf8.elementsEqual("e\u{301}".utf8) == true)
            try await current.succeed(["新建议"])
            try await awaitHistory { !h.model.state.loading }
            try await h.model.choose("新建议", context: #require(h.model.state.context), style: "标准")
            h.model.confirmChoice(style: "标准")
            let stream = try await nextTurn { await h.base.turnGateway.popStream() }
            #expect(stream.request.model?.utf8.elementsEqual("e\u{301}".utf8) == true)
            #expect(stream.request.input == "新建议")
        }
    }

    @Test
    func unavailableChoiceDisablesSuggestionsAndIgnoresLateGeneratedSuggestion() async throws {
        try await withSuggestions { h in
            h.model.setModel("env:first"); h.model.setActive(true)
            let read = try await h.gateway.next(), context = try #require(h.model.state.context)
            h.base.turn.setModelSelection(account: context.account, model: "env:first", available: false)
            h.model.refresh()
            try await read.succeed(["迟到建议"])
            try await awaitHistory { await read.completed }; await Task.yield()
            #expect(!h.model.state.enabled)
            await h.model.choose("迟到建议", context: context, style: "标准")
            #expect(await h.base.turnGateway.streamCount == 0)
            #expect(await h.gateway.count == 1)
        }
    }
}
