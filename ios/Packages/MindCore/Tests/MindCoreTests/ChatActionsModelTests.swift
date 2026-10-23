import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatActionsModelTests {
    @Test func unconsumedReceiptAndStaleLeasesCannotOpenMutationGate() async throws {
        try await withTurn { h in
            try await h.login(); try await h.ready()
            try await h.begin().continuation.finish()
            try await h.resolve(h.status())
            let account = try #require(h.model.state.account)
            #expect(h.model.reserveHistoryMutation(account) == nil)
            try h.model.acknowledge(#require(h.model.state.receipt))
            let first = try #require(h.model.reserveHistoryMutation(account))
            #expect(!h.model.state.canSend)
            h.model.releaseHistoryMutation(first)
            let second = try #require(h.model.reserveHistoryMutation(account))
            h.model.releaseHistoryMutation(first)
            #expect(h.model.state.changingHistory)
            h.model.releaseHistoryMutation(second)
            #expect(h.model.state.editable)
        }
    }

    @Test func currentUnauthorizedClearsPresentationWithoutApplyingResult() async throws {
        try await withActions { h in
            try await h.login(); h.model.rename("main"); h.model.editTitle("标题"); h.model.confirm()
            try await h.next().finish(.failure(sessionHTTPFailure(401)))
            try await awaitHistory { h.model.state.account == nil }
            #expect(await h.session.state == .signedOut(expired: true))
            #expect(h.model.state.dialog == nil); #expect(h.history.model.state.selected?.title == nil)
        }
    }

    @Test func renameBlocksSendingAndLateSummariesWithoutLosingDraft() async throws {
        try await withActions { h in
            try await h.login(); h.history.model.refreshConversations()
            let stale = try await h.history.conversations()
            h.model.rename("main"); h.model.editTitle(String(repeating: "🙂", count: 41)); h.model.confirm()
            #expect(!h.model.state.canConfirm); #expect(await h.gateway.count == 0)
            h.model.editTitle("手动标题"); h.model.confirm(); h.model.confirm()
            let write = try await h.next()
            #expect(!h.turn.state.editable)
            h.turn.send(style: "标准"); try h.turn.select(ChatTarget(sessionID: "other")); h.turn.edit("覆盖草稿")
            #expect(await h.turnGateway.streamCount == 0)
            #expect(h.turn.state.target?.sessionID == "main"); #expect(h.turn.state.draft == "未发送的草稿")
            try await write.finish(.success(manualTitle()))
            try await awaitHistory { !h.model.state.busy }
            try await stale.succeed([historySummary(104, "main")])
            try await awaitHistory { await stale.completed }; await Task.yield()
            #expect(h.history.model.state.selected?.title == "手动标题")
            #expect(h.history.model.state.conversations.items.first?.title == "手动标题")
            #expect(h.turn.state.editable); #expect(await h.gateway.count == 1)
        }
    }

    @Test func sessionDeletionRequiresConfirmationAndClearsDeletedTarget() async throws {
        try await withActions { h in
            try await h.login(); h.model.deleteSession("main"); h.model.cancelDialog(); await Task.yield()
            #expect(await h.gateway.count == 0); #expect(h.history.model.state.selected != nil)
            h.history.model.refreshMessages(); let stale = try await h.history.messages()
            h.model.deleteSession("main")
            #expect(h.model.state.dialog == .deleteSession(sessionID: "main", title: "", discardsDraft: true))
            h.model.confirm(); let write = try await h.next()
            h.model.cancelDialog(); #expect(h.model.state.busy)
            await write.finish(.success(nil)); try await awaitHistory { !h.model.state.busy }
            #expect(h.history.model.state.selected == nil); #expect(h.turn.state.target == nil)
            #expect(h.turn.state.draft.isEmpty)
            #expect(h.history.model.state.conversations.items.map(\.sessionID) == ["other"])
            try await stale.succeed([historyMessage(104, "main")])
            try await awaitHistory { await stale.completed }; await Task.yield()
            #expect(h.history.model.state.messages.items.isEmpty)
            try await h.history.conversations().succeed([historySummary(90, "other")])
        }
    }

    @Test func batchDeletionRemovesConfirmedIDsAndInvalidatesStaleReads() async throws {
        try await withActions { h in
            try await h.login(); h.model.selectMessages()
            h.model.toggleMessage(999); h.model.toggleMessage(103); h.model.toggleMessage(101)
            #expect(h.model.state.selectedIDs == [101, 103])
            h.history.model.refreshMessages(); let stale = try await h.history.messages()
            h.model.deleteSelectedMessages(); h.model.confirm(); let write = try await h.next()
            #expect(await write.ids == [101, 103])
            await write.finish(.success(nil)); try await awaitHistory { !h.model.state.busy }
            #expect(h.history.model.state.messages.items.map(\.id) == [104, 102])
            #expect(h.turn.state.draft == "未发送的草稿"); #expect(h.model.state.selectionSessionID == nil)
            try await stale.succeed([historyMessage(103, "main")])
            try await awaitHistory { await stale.completed }; await Task.yield()
            #expect(h.history.model.state.messages.items.map(\.id) == [104, 102])
            try await h.history.messages().succeed([historyMessage(104, "main"), historyMessage(102, "main")])
            try await h.history.conversations().succeed([historySummary(104, "main")])
        }
    }

    @Test func failedMutationPreservesIntentAndRequiresExplicitRetry() async throws {
        try await withActions { h in
            try await h.login(); h.model.rename("main"); h.model.editTitle("重试标题"); h.model.confirm()
            try await h.next().finish(.failure(URLError(.networkConnectionLost)))
            try await awaitHistory { !h.model.state.busy }
            #expect(h.model.state.dialog == .rename(sessionID: "main", title: "重试标题"))
            #expect(h.model.state.notice != nil); #expect(h.turn.state.editable)
            #expect(h.history.model.state.selected?.title == nil)
            await Task.yield(); #expect(await h.gateway.count == 1)
            h.model.confirm(); try await h.next().finish(.success(manualTitle("重试标题")))
            try await awaitHistory { !h.model.state.busy }
            #expect(await h.gateway.count == 2); #expect(h.history.model.state.selected?.title == "重试标题")
        }
    }

    @Test func activeTurnCannotBeModified() async throws {
        try await withActions { h in
            try await h.login(); h.model.deleteSession("main")
            h.turn.send(style: "标准"); _ = try await nextTurn { await h.turnGateway.popStream() }
            h.model.confirm(); await Task.yield()
            #expect(!h.model.state.busy); #expect(await h.gateway.count == 0); #expect(h.model.state.notice != nil)
            h.model.cancelDialog(); h.model.rename("main"); #expect(h.model.state.dialog == nil)
        }
    }

    @Test(arguments: [false, true])
    func lateOldAccountCannotMutateOrUnlockNextAccount(unauthorized: Bool) async throws {
        try await withActions { h in
            try await h.login(); h.model.rename("main"); h.model.editTitle("旧标题"); h.model.confirm()
            let old = try await h.next()
            try await h.login(2); h.model.rename("main"); h.model.editTitle("新标题"); h.model.confirm()
            let current = try await h.next()
            if unauthorized {
                await old.finish(.failure(sessionHTTPFailure(401)))
            } else {
                try await old.finish(.success(manualTitle("旧标题")))
            }
            try await awaitHistory { await old.completed }; await Task.yield()
            #expect(h.model.state.busy); #expect(h.turn.state.changingHistory)
            #expect(await HistoryAccount.from(h.session.state)?.userID == 2)
            #expect(h.history.model.state.selected?.title == nil)
            try await current.finish(.success(manualTitle("新标题")))
            try await awaitHistory { !h.model.state.busy }
            #expect(h.history.model.state.selected?.title == "新标题")
        }
    }

    @Test func selectionIsBoundedAndMembershipRechecked() async throws {
        try await withActions { h in
            try await h.login(); h.history.model.refreshMessages()
            try await h.history.messages().succeed(
                (102 ... 201).reversed().map { try historyMessage(Int64($0), "main") },
                cursor: HistoryCursor(snapshotID: 201, beforeID: 102)
            )
            try await awaitHistory { h.history.model.state.messages.loading == nil }
            h.history.model.loadMoreMessages(); try await h.history.messages().succeed([historyMessage(101, "main")])
            try await awaitHistory { h.history.model.state.messages.items.count == 101 }
            h.model.selectMessages(); (101 ... 201).forEach { h.model.toggleMessage(Int64($0)) }
            #expect(h.model.state.selectedIDs.count == 100); #expect(h.model.state.notice != nil)
            h.model.deleteSelectedMessages()
            h.history.model.refreshMessages(); try await h.history.messages().succeed([historyMessage(201, "main")])
            try await awaitHistory { h.history.model.state.messages.loading == nil }
            h.model.confirm(); await Task.yield()
            #expect(await h.gateway.count == 0); #expect(h.model.state.notice != nil)
            h.model.cancelDialog(); h.model.deleteSelectedMessages()
            #expect(h.model.state.selectedIDs.isEmpty); #expect(h.model.state.dialog == nil)
        }
    }

    @Test func otherConversationDeletionPreservesDraftAndEmptyDraftIsNotManaged() async throws {
        try await withActions { h in
            try await h.login(); #expect(!h.model.canManage("unknown"))
            h.model.deleteSession("other"); h.model.confirm(); try await h.next().finish(.success(nil))
            try await awaitHistory { !h.model.state.busy }
            #expect(h.turn.state.target?.sessionID == "main"); #expect(h.turn.state.draft == "未发送的草稿")
            var row = try historySummary(104, "main"); row.title = "自动标题"
            try await h.history.conversations().succeed([row])
            try await awaitHistory { h.history.model.state.selected?.title == "自动标题" }
            let target = try ChatTarget(sessionID: "empty")
            h.history.model.openConversation(target); h.turn.select(target)
            try await h.history.messages().succeed([]); try await awaitHistory { h.history.model.state.messages.loaded }
            #expect(!h.model.canManage("empty")); h.model.rename("empty"); #expect(h.model.state.dialog == nil)
        }
    }
}
