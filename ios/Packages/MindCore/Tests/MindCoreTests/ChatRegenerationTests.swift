import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatRegenerationTests {
    @Test
    func activeRowIsHiddenByRequestIDBeforeMessageIDsArrive() throws {
        let source = try history()
        let pending = try PendingChatTurn(ownerID: 1, target: turnRequest().pending.target,
                                          requestID: "regen", regenerateMessageID: 102)
        let active = try changed(source.messages.items[1], id: 103, metadata: ["request_id": pending.requestID])
        var state = ChatTurnState()
        state.pending = pending
        #expect((source.messages.items + [active]).filter(state.showsInHistory) == source.messages.items)
        let receipt = ChatTurnReceipt(
            pending: pending,
            status: .failed,
            messages: Array(source.messages.items.prefix(1))
        )
        #expect((source.messages.items + [active]).filter(receipt.retains) == source.messages.items)
        let missingReplacement = ChatTurnReceipt(pending: pending, status: .complete, messages: receipt.messages)
        #expect((source.messages.items + [active])
            .filter(missingReplacement.retains) == Array(source.messages.items.prefix(1)))
        #expect(ChatTurnState().showsInHistory(active))
    }

    private func history(account: HistoryAccount = HistoryAccount(userID: 1, revision: 1)) throws -> ChatLibraryState {
        var history = ChatLibraryState()
        history.account = account
        history.selected = try ChatConversation(target: turnRequest().pending.target, title: nil)
        history.messages.items = try turnFixture().messages
        history.messages.loaded = true
        return history
    }

    private func changed(_ message: StoredChatMessage, id: Int64? = nil, metadata: [String: String]? = nil,
                         session: String? = nil, attachments: [[String: String]]? = nil) throws -> StoredChatMessage
    {
        let value: [String: Any] = ["id": id ?? message.id, "role": message.role, "content": message.content,
                                    "node_key": message.nodeKey, "mode": message.mode, "topic_id": NSNull(),
                                    "session_id": session ?? message.sessionID, "message_type": message.messageType,
                                    "metadata": metadata as Any? ?? NSNull(), "created_at": NSNull(),
                                    "attachments": attachments ?? []]
        return try JSONDecoder().decode(StoredChatMessage.self, from: JSONSerialization.data(withJSONObject: value))
    }

    @Test
    func latestQuestionRequiresCompleteCompatibleContextAndKeepsWhitespace() throws {
        var source = try history()
        #expect(ChatRegeneration.from(source)?.answerID == 102)
        #expect(try ChatRegeneration.from(source)?.input == turnRequest().input)
        source.messages.loading = .refresh
        #expect(ChatRegeneration.from(source) == nil)
        source.messages.loading = nil
        let user = source.messages.items[0], answer = source.messages.items[1]
        let invalid: [[StoredChatMessage]] = try [
            [answer], [user], [changed(user, id: 103), answer], [changed(user, session: "other"), answer],
            [changed(user, metadata: ["kind": "node_overview"]), answer],
            [changed(user, metadata: ["quote": "quote"]), answer],
            [changed(user, attachments: [[:]]), answer],
            [user, changed(answer, metadata: ["status": "generating"])],
        ]
        for items in invalid {
            source.messages.items = items
            #expect(ChatRegeneration.from(source) == nil)
        }
    }

    @Test
    func regenerationPreservesDraftSavesBeforePOSTAndBlocksDoubleTap() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            h.model.edit("未发送草稿")
            let source = try history(account: #require(h.model.state.account))
            h.model.regenerate(history: source, style: "标准")
            let stream = try await nextTurn { await h.gateway.popStream() }
            #expect(stream.saved?.regenerateMessageID == 102)
            #expect(try stream.request.input == turnRequest().input)
            #expect(h.model.state.draft == "未发送草稿")
            h.model.regenerate(history: source, style: "标准"); h.model.send(style: "标准")
            #expect(await h.gateway.streamCount == 0)
            stream.continuation.yield(.messageIDs(user: 101, ai: 103))
            stream.continuation.yield(.text("新回答")); stream.continuation.finish()
            try await h.status().finish(.success(RemoteChatTurn(
                status: .complete,
                ids: ChatMessageIDs(user: 101, ai: 103)
            )))
            let read = try await nextTurn { await h.gateway.popMessages() }
            try await read
                .finish(.success(source.messages.items.map { $0.role == "ai" ? try changed($0, id: 103) : $0 }))
            try await awaitHistory { h.model.state.editable }
            #expect(h.model.state.receipt?.replacedMessageID == 102)
            #expect(h.model.state.draft == "未发送草稿")
        }
    }

    @Test(arguments: [ChatTurnStatus.complete, .failed, .interrupted])
    func historyOnlyReplacesAfterSuccessAndRejectsLatePage(status: ChatTurnStatus) async throws {
        try await withHistory { h in
            try await h.login(); try await h.conversations().succeed([])
            let source = try history()
            try h.model.openConversation(#require(source.selected).target)
            let active = try changed(source.messages.items[1], id: 103, metadata: ["request_id": "regen"])
            try await h.messages().succeed(source.messages.items + [active])
            try await awaitHistory { h.model.state.messages.loaded }
            h.model.refreshMessages()
            let stale = try await h.messages()
            let pending = try PendingChatTurn(ownerID: 1, target: #require(source.selected).target,
                                              requestID: "regen", regenerateMessageID: 102)
            let receipt = try ChatTurnReceipt(pending: pending, status: status,
                                              messages: source.messages.items.map { $0.role == "ai" ? try changed(
                                                  $0,
                                                  id: 103
                                              ) : $0 })
            let account = try #require(h.model.state.account)
            h.model.accept(receipt, account: account)
            let expected: [Int64] = status == .complete ? [103, 101] : [102, 101]
            #expect(h.model.state.messages.items.map(\.id) == expected)
            await stale.succeed(source.messages.items)
            try await awaitHistory { await stale.completed }
            #expect(h.model.state.messages.items.map(\.id) == expected)
            h.model.accept(receipt, account: account)
            #expect(h.model.state.messages.items.map(\.id) == expected)
        }
    }

    @Test
    func restoredRegenerationQueriesOnlyAndStopPreservesOriginal() async throws {
        let journal = MemoryTurnJournal()
        let pending = try PendingChatTurn(ownerID: 1, target: turnRequest().pending.target,
                                          requestID: "regen", regenerateMessageID: 102)
        try await journal.save(pending)
        try await withTurn(journal) { h in
            try await h.login()
            let read = try await h.status()
            #expect(read.pending.regenerateMessageID == 102)
            try await read.finish(.success(RemoteChatTurn(
                status: .generating,
                ids: ChatMessageIDs(user: 101, ai: 103)
            )))
            try await awaitHistory { h.model.state.canVerify }
            h.model.stop()
            try await h.cancel().finish(.success(RemoteChatTurn(
                status: .interrupted,
                ids: ChatMessageIDs(user: 101, ai: 103)
            )))
            let message = try await nextTurn { await h.gateway.popMessages() }
            try await message.finish(.success(Array(history().messages.items.prefix(1))))
            try await awaitHistory { h.model.state.editable }
            #expect(h.model.state.receipt?.replacedMessageID == nil)
            #expect(h.model.state.notice?.contains("原回答") == true)
            #expect(await h.gateway.streamCount == 0)
            #expect(try await journal.read(ownerID: 1) == nil)
        }
    }

    @Test
    func staleQuestionRejectionPersistsStopTombstoneBeforeClearingRecovery() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            try h.model.regenerate(history: history(account: #require(h.model.state.account)), style: "标准")
            let stream = try await nextTurn { await h.gateway.popStream() }
            stream.continuation.finish(throwing: HTTPFailure(
                status: 409,
                code: "CHAT_REGENERATE_NOT_LATEST",
                userMessage: "stale",
                retryable: false
            ))
            let stop = try await h.cancel()
            #expect(try await h.journal.read(ownerID: 1) == stop.pending)
            await stop.finish(.success(RemoteChatTurn(status: .interrupted, ids: nil)))
            try await awaitHistory { h.model.state.editable }
            #expect(try await h.journal.read(ownerID: 1) == nil)
            #expect(h.model.state.receipt?.replacedMessageID == nil)
            #expect(await h.gateway.statusCount == 0)
        }
    }

    @Test
    func oldAccountCandidateOrDifferentTargetCannotStartRegeneration() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            let account = try #require(h.model.state.account)
            try h.model.regenerate(
                history: history(account: HistoryAccount(userID: account.userID, revision: account.revision + 1)),
                style: "标准"
            )
            try h.model.select(ChatTarget(sessionID: "different"))
            try h.model.regenerate(history: history(account: account), style: "标准")
            await Task.yield()
            #expect(await h.gateway.streamCount == 0)
            #expect(try await h.journal.read(ownerID: 1) == nil)
        }
    }
}
