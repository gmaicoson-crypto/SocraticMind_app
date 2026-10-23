import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatLibraryModelTests {
    @Test func emptyFailureAndRetry() async throws {
        try await withHistory { h in
            h.model.refreshConversations()
            #expect(await h.gateway.conversationCount == 0)
            try await h.login()
            #expect(h.model.state.conversations.loading == .refresh)
            let first = try await h.conversations()
            await h.model.bindAccount(h.session.state)
            h.model.refreshConversations()
            #expect(await h.gateway.conversationCount == 0)
            await first.finish(.failure(SessionTestError.offline))
            try await awaitHistory { h.model.state.conversations.failure != nil }
            #expect(!h.model.state.conversations.loaded)
            #expect(!String(describing: h.model.state).contains("synthetic-token"))
            h.model.refreshConversations()
            try await h.conversations().succeed([])
            try await awaitHistory { h.model.state.conversations.loaded }
            #expect(h.model.state.conversations.failure == nil)
            #expect(h.model.state.conversations.items.isEmpty)
        }
    }

    @Test func paginationDeduplicatesAndKeepsNewerSummary() async throws {
        try await withHistory { h in
            try await h.login()
            let cursor = try HistoryCursor(snapshotID: 100, beforeID: 90)
            try await h.conversations().succeed([historySummary(100), historySummary(90, "b")], cursor: cursor)
            try await awaitHistory { h.model.state.conversations.loaded }
            h.model.loadMoreConversations()
            let more = try await h.conversations()
            #expect(more.cursor == cursor)
            h.model.loadMoreConversations()
            #expect(await h.gateway.conversationCount == 0)
            try await more.succeed([historySummary(80, preview: "旧内容"), historySummary(70, "c")])
            try await awaitHistory { h.model.state.conversations.loading == nil }
            #expect(h.model.state.conversations.items.map(\.sessionID) == ["a", "b", "c"])
            #expect(h.model.state.conversations.items.first?.lastMessageID == 100)
            h.model.loadMoreConversations()
            #expect(await h.gateway.conversationCount == 0)
        }
    }

    @Test func failedMoreRetainsItemsAndCursor() async throws {
        try await withHistory { h in
            try await h.login()
            let cursor = try HistoryCursor(snapshotID: 100, beforeID: 90)
            try await h.conversations().succeed([historySummary(90)], cursor: cursor)
            try await awaitHistory { h.model.state.conversations.loaded }
            h.model.loadMoreConversations()
            try await h.conversations().finish(.failure(SessionTestError.offline))
            try await awaitHistory { h.model.state.conversations.failure != nil }
            #expect(h.model.state.conversations.failure?.operation == .more)
            #expect(h.model.state.conversations.items.map(\.lastMessageID) == [90])
            h.model.loadMoreConversations()
            let retry = try await h.conversations()
            #expect(retry.cursor == cursor)
            try await retry.succeed([historySummary(80, "b")])
            try await awaitHistory { h.model.state.conversations.loading == nil }
            #expect(h.model.state.conversations.items.count == 2)
        }
    }

    @Test func refreshDropsLateOlderPage() async throws {
        try await withHistory { h in
            try await h.login()
            try await h.conversations().succeed(
                [historySummary(90)],
                cursor: HistoryCursor(snapshotID: 100, beforeID: 90)
            )
            try await awaitHistory { h.model.state.conversations.loaded }
            h.model.loadMoreConversations()
            let old = try await h.conversations()
            h.model.refreshConversations()
            let refresh = try await h.conversations()
            #expect(refresh.cursor == nil)
            try await refresh.succeed([historySummary(110)])
            try await awaitHistory { h.model.state.conversations.loading == nil }
            try await old.succeed([historySummary(80, "old")])
            try await awaitHistory { await old.completed }
            #expect(h.model.state.conversations.items.map(\.lastMessageID) == [110])
            #expect(h.model.state.conversations.failure == nil)
        }
    }

    @Test func switchingAndClosingDropLateResultsAndErrors() async throws {
        try await withHistory { h in
            try await h.login()
            try await h.conversations().succeed([historySummary(100), historySummary(90, "b")])
            try await awaitHistory { h.model.state.conversations.loaded }
            h.model.selectConversation("unknown")
            #expect(h.model.state.selected == nil)
            h.model.selectConversation("a")
            let old = try await h.messages()
            #expect(old.sessionID == "a")
            h.model.selectConversation("b")
            let current = try await h.messages()
            #expect(h.model.state.messages.items.isEmpty)
            try await current.succeed([historyMessage(90, "b")])
            try await awaitHistory { h.model.state.messages.loaded }
            await old.finish(.failure(SessionTestError.offline))
            try await awaitHistory { await old.completed }
            #expect(h.model.state.messages.items.map(\.sessionID) == ["b"])
            #expect(h.model.state.messages.failure == nil)
            h.model.refreshMessages()
            let closing = try await h.messages()
            h.model.closeConversation()
            try await closing.succeed([historyMessage(90, "b")])
            try await awaitHistory { await closing.completed }
            #expect(h.model.state.selected == nil)
            #expect(h.model.state.messages.items.isEmpty)
        }
    }

    @Test func messageMergeAndRefreshFailure() async throws {
        try await withHistory { h in
            try await h.login()
            try await h.conversations().succeed([historySummary(100)])
            try await awaitHistory { h.model.state.conversations.loaded }
            h.model.selectConversation("a")
            let cursor = try HistoryCursor(snapshotID: 100, beforeID: 90)
            try await h.messages().succeed([historyMessage(100, "a"), historyMessage(90, "a")], cursor: cursor)
            try await awaitHistory { h.model.state.messages.loaded }
            h.model.loadMoreMessages()
            let next = try await h.messages()
            #expect(next.cursor == cursor)
            try await next.succeed([historyMessage(90, "a"), historyMessage(80, "a")])
            try await awaitHistory { h.model.state.messages.loading == nil }
            #expect(h.model.state.messages.items.map(\.id) == [100, 90, 80])
            h.model.refreshMessages()
            try await h.messages().finish(.failure(SessionTestError.offline))
            try await awaitHistory { h.model.state.messages.failure != nil }
            #expect(h.model.state.messages.failure?.operation == .refresh)
            #expect(h.model.state.messages.items.count == 3)
        }
    }

    @Test func accountChangeClearsHistoryAndRejectsOld401() async throws {
        try await withHistory { h in
            try await h.login()
            try await h.conversations().succeed([historySummary(100, "shared")])
            try await awaitHistory { h.model.state.conversations.loaded }
            h.model.selectConversation("shared")
            let old = try await h.messages()
            h.model.clear()
            #expect(h.model.state.account == nil)
            #expect(h.model.state.conversations.items.isEmpty)
            try await h.session.logout()
            try await h.login(2)
            let fresh = try await h.conversations()
            #expect(fresh.token == "synthetic-token-2")
            try await fresh.succeed([historySummary(100, "shared", preview: "账号二")])
            try await awaitHistory { h.model.state.conversations.loaded }
            await old.finish(.failure(sessionHTTPFailure(401)))
            try await awaitHistory { await old.completed }
            #expect(await HistoryAccount.from(h.session.state)?.userID == 2)
            #expect(h.model.state.conversations.items.first?.preview == "账号二")
            #expect(h.model.state.selected == nil)
            #expect(h.model.state.messages.items.isEmpty)
        }
    }

    @Test func current401ClearsBeforeAppObservation() async throws {
        try await withHistory { h in
            try await h.login()
            try await h.conversations().finish(.failure(sessionHTTPFailure(401)))
            try await awaitHistory { h.model.state.account == nil }
            #expect(await h.session.state == .signedOut(expired: true))
            #expect(h.model.state.conversations.items.isEmpty)
        }
    }

    @Test func closedModelCannotResume() async throws {
        try await withHistory { h in
            try await h.login()
            let pending = try await h.conversations()
            h.model.close()
            try await pending.succeed([historySummary(100)])
            try await awaitHistory { await pending.completed }
            await h.model.bindAccount(h.session.state)
            h.model.refreshConversations()
            #expect(h.model.state.account == nil)
            #expect(h.model.state.conversations.items.isEmpty)
            #expect(await h.gateway.conversationCount == 0)
        }
    }
}
