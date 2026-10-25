import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatFeedbackStateTests {
    @Test
    func confirmedFeedbackWinsOverLiveHintsWithoutRetryingRequest() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            let stream = try await h.begin()
            stream.continuation.yield(.failure(
                code: "AI_QUOTA_EXCEEDED",
                message: "synthetic-private-key",
                retryable: false
            ))
            stream.continuation.finish()
            let status = try await h.status()
            #expect(h.model.state.receipt == nil && !h.model.state.canSend)
            try await status.finish(.success(RemoteChatTurn(
                status: .interrupted,
                ids: ChatMessageIDs(user: 101, ai: 102),
                feedback: feedbackValue("AI_TIMEOUT")
            )))
            let messages = try await nextTurn { await h.gateway.popMessages() }
            try await messages.finish(.success(turnFixture().messages))
            try await awaitHistory { h.model.state.editable }
            let notice = try #require(h.model.state.notice)
            #expect(notice.contains("超时") && !notice.contains("额度不足") && !notice.contains("synthetic-private-key"))
            #expect(await h.gateway.streamCount == 0)
            #expect(await h.journal.records[1] == nil)
            try h.model.select(ChatTarget(sessionID: "different-session"))
            #expect(h.model.state.notice == nil)
            h.model.clear()
            #expect(h.model.state.receipt == nil)
        }
    }

    @Test
    func failedRegenerationReportsHiddenAttemptAndPreservesOldAnswerAndDraft() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready(); h.model.edit("独立草稿")
            let originals = try turnFixture().messages
            var source = ChatLibraryState()
            source.account = h.model.state.account
            source.selected = try ChatConversation(target: turnRequest().pending.target, title: nil)
            source.messages.items = originals; source.messages.loaded = true
            h.model.regenerate(history: source, style: "标准")
            let stream = try await nextTurn { await h.gateway.popStream() }
            stream.continuation.finish()
            try await h.status().finish(.success(RemoteChatTurn(
                status: .failed,
                ids: ChatMessageIDs(user: 101, ai: 103),
                feedback: feedbackValue("AI_QUOTA_EXCEEDED")
            )))
            let messages = try await nextTurn { await h.gateway.popMessages() }
            await messages.finish(.success(originals.filter { $0.role == "user" }))
            try await awaitHistory { h.model.state.editable }
            let notice = try #require(h.model.state.notice)
            #expect(notice.contains("额度不足") && notice.contains("原回答仍保留") && notice.contains("合计 59"))
            #expect(notice.contains(ChatAnswerFeedback.scopeNote))
            #expect(h.model.state.draft == "独立草稿")
            let receipt = try #require(h.model.state.receipt)
            #expect(receipt.replacedMessageID == nil)
            #expect(originals.filter(receipt.retains) == originals)
            #expect(await h.gateway.streamCount == 0)
        }
    }

    @Test
    func cancelRecoveryUsesStoredReasonAndMissingMessagesKeepDeletionNotice() throws {
        let messages = try turnFixture().messages
        let pending = try turnRequest().pending
        let stopped = try RemoteChatTurn(
            status: .interrupted,
            ids: ChatMessageIDs(user: 101, ai: 102),
            feedback: feedbackValue("USER_CANCELLED")
        )
        #expect(ChatTurnOutcome.notice(pending: pending, remote: stopped, messages: messages, rejectedModel: false)?
            .contains("已停止") == true)
        #expect(ChatTurnOutcome.notice(pending: pending, remote: stopped, messages: [], rejectedModel: false)?
            .contains("更新或删除") == true)
        #expect(ChatTurnOutcome.notice(pending: pending, remote: stopped, messages: messages, rejectedModel: true)?
            .contains("模型不可用") == true)
        #expect(ChatTurnOutcome.notice(
            pending: pending,
            remote: RemoteChatTurn(status: .complete, ids: stopped.ids, feedback: stopped.feedback),
            messages: messages,
            rejectedModel: false
        ) == nil)
    }
}
