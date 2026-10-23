import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatTitleRefreshTests {
    @Test
    func batchShrinksToPendingJobsAndUpdatesSelectedTitle() async throws {
        try await prepared { h in
            h.model.refreshConversations()
            try await h.conversations().succeed([historySummary(4, "a"), historySummary(3, "b"),
                                                 historySummary(2, "c"), historySummary(1, "missing")])
            try await awaitHistory { h.model.state.conversations.loading == nil }
            h.model.selectConversation("a"); try await h.messages().succeed([])
            h.model.setTitlePollingActive(true)
            let first = try await h.titles.next()
            #expect(first.ids == ["a", "b", "c", "missing"])
            try await first.read.succeed([title("a", text: "标题a"), title("b", status: .running, text: nil),
                                          title("c", status: .failed, text: nil, retry: true)])
            let second = try await h.titles.next()
            #expect(second.ids == ["b", "c"])
            #expect(h.model.state.selected?.title == "标题a")
            try await second.read.succeed([title("b", status: .failed, text: nil), title("c")])
            try await awaitHistory { !h.model.state.refreshingTitles }
            #expect(h.model.state.titleNotice?.contains("失败") == true)
            #expect(await h.titles.count == 2)
            #expect(h.model.state.conversations.items.count == 4)
        }
    }

    @Test
    func eightReadBudgetRequiresExplicitRefreshToRestart() async throws {
        try await prepared { h in
            h.model.setTitlePollingActive(true)
            for _ in 0 ..< 8 {
                try await h.titles.next().read.succeed([title("a", status: .pending, text: nil)])
            }
            try await awaitHistory { !h.model.state.refreshingTitles }
            #expect(h.model.state.titleNotice?.contains("稍后刷新") == true)
            for _ in 0 ..< 3 {
                h.model.setTitlePollingActive(true)
            }
            await Task.yield()
            #expect(await h.titles.count == 8)
            h.model.refreshConversations()
            try await h.conversations().succeed([historySummary(2, "a")])
            try await h.titles.next().read.succeed([])
            try await awaitHistory { !h.model.state.refreshingTitles }
            #expect(await h.titles.count == 9)
            #expect(h.model.state.titleNotice == nil)
        }
    }

    @Test
    func hiddenViewCancelsAndLateResultCannotReplaceResumedCycle() async throws {
        try await prepared { h in
            #expect(await h.titles.count == 0)
            h.model.setTitlePollingActive(true)
            let old = try await h.titles.next()
            h.model.setTitlePollingActive(false)
            #expect(!h.model.state.refreshingTitles)
            h.model.setTitlePollingActive(true)
            let fresh = try await h.titles.next()
            try await old.read.succeed([title("a", text: "过期")])
            try await awaitHistory { await old.read.completed }
            #expect(h.model.state.conversations.items.first?.title == nil)
            #expect(h.model.state.refreshingTitles)
            try await fresh.read.succeed([title("a", text: "最新")])
            try await awaitHistory { !h.model.state.refreshingTitles }
            #expect(h.model.state.conversations.items.first?.title == "最新")
        }
    }

    @Test
    func manualRenameFencesLateAutomaticTitle() async throws {
        try await prepared { h in
            h.model.selectConversation("a"); try await h.messages().succeed([])
            h.model.setTitlePollingActive(true)
            let old = try await h.titles.next()
            try h.model.accept(.renamed(title("a", status: .manual, text: "手动")),
                               account: #require(h.model.state.account))
            try await old.read.succeed([title("a", text: "旧自动")])
            try await awaitHistory { await old.read.completed }
            #expect(h.model.state.selected?.title == "手动")
            #expect(h.model.state.conversations.items.first?.titleStatus == "manual")
            #expect(!h.model.state.refreshingTitles)
        }
    }

    @Test
    func deletionCannotBeUndoneByLateTitle() async throws {
        try await prepared { h in
            h.model.setTitlePollingActive(true)
            let old = try await h.titles.next()
            try h.model.accept(.deletedSession("a"), account: #require(h.model.state.account))
            try await h.conversations().succeed([])
            try await old.read.succeed([title("a")])
            try await awaitHistory { await old.read.completed && h.model.state.conversations.loading == nil }
            #expect(h.model.state.conversations.items.isEmpty)
            #expect(!h.model.state.refreshingTitles)
        }
    }

    @Test
    func freshConversationResponseWinsOverEarlierTitleRead() async throws {
        try await prepared { h in
            h.model.setTitlePollingActive(true)
            let old = try await h.titles.next()
            h.model.refreshConversations()
            var row = try historySummary(2, "a"); row.title = "另一设备手动"; row.titleStatus = "manual"
            try await h.conversations().succeed([row])
            try await awaitHistory { h.model.state.conversations.loading == nil }
            try await old.read.succeed([title("a", text: "旧生成")])
            try await awaitHistory { await old.read.completed }
            #expect(h.model.state.conversations.items.first?.title == "另一设备手动")
            #expect(await h.titles.count == 1)
        }
    }

    @Test(arguments: [false, true])
    func accountRevisionRejectsOldSuccessAndUnauthorizedResult(unauthorized: Bool) async throws {
        try await prepared { h in
            h.model.setTitlePollingActive(true)
            let old = try await h.titles.next()
            h.model.clear(); try await h.session.logout(); try await h.login(2)
            try await h.conversations().succeed([historySummary(2, "a")])
            let fresh = try await h.titles.next()
            #expect(fresh.read.token == "synthetic-token-2")
            if unauthorized {
                await old.read.finish(.failure(sessionHTTPFailure(401)))
            } else {
                try await old.read.succeed([title("a", text: "账号一")])
            }
            try await awaitHistory { await old.read.completed }
            #expect(await HistoryAccount.from(h.session.state)?.userID == 2)
            #expect(h.model.state.conversations.items.first?.title == nil)
            try await fresh.read.succeed([title("a", text: "账号二")])
            try await awaitHistory { !h.model.state.refreshingTitles }
            #expect(h.model.state.conversations.items.first?.title == "账号二")
        }
    }

    @Test
    func current401ClearsBeforeAppObservation() async throws {
        try await prepared { h in
            h.model.setTitlePollingActive(true)
            try await h.titles.next().read.finish(.failure(sessionHTTPFailure(401)))
            try await awaitHistory { h.model.state.account == nil }
            #expect(await h.session.state == .signedOut(expired: true))
            #expect(h.model.state.conversations.items.isEmpty)
        }
    }

    @Test
    func readFailureStopsWithoutClearingHistoryOrAutomaticRetry() async throws {
        try await prepared { h in
            h.model.setTitlePollingActive(true)
            try await h.titles.next().read.finish(.failure(SessionTestError.offline))
            try await awaitHistory { !h.model.state.refreshingTitles }
            #expect(h.model.state.titleNotice?.contains("失败") == true)
            #expect(await h.titles.count == 1)
            #expect(h.model.state.conversations.items.count == 1)
        }
    }

    @Test
    func openingAndRefreshingOlderSelectedConversationKeepsTitleEligible() async throws {
        try await prepared { h in
            h.model.setTitlePollingActive(true)
            try await h.titles.next().read.succeed([])
            try await awaitHistory { !h.model.state.refreshingTitles }
            h.model.selectConversation("a"); try await h.messages().succeed([])
            try await awaitHistory { h.model.state.messages.loaded }
            let old = try await h.titles.next()
            h.model.refreshSelectedConversation(); try await h.messages().succeed([])
            var newer = try historySummary(2, "newer"); newer.title = "完成"; newer.titleStatus = "ready"
            try await h.conversations().succeed([newer])
            let selected = try await h.titles.next()
            #expect(selected.ids == ["a"])
            try await old.read.succeed([title("a", text: "过期")])
            try await selected.read.succeed([title("a", text: "旧会话新标题")])
            try await awaitHistory { !h.model.state.refreshingTitles }
            #expect(h.model.state.selected?.title == "旧会话新标题")
            #expect(h.model.state.conversations.items.map(\.sessionID) == ["newer"])
        }
    }

    @Test
    func candidateCapPrioritizesSelectedAndNewPageAndKeepsTerminalRows() throws {
        var rows = try (1 ... 130).map { try historySummary(Int64($0), "s\($0)") }
        var ready = try historySummary(131, "ready"); ready.title = "完成"; ready.titleStatus = "ready"
        var manual = try historySummary(132, "manual"); manual.title = "手动"; manual.titleStatus = "manual"
        rows += [ready, manual]
        var state = ChatLibraryState()
        state.conversations.items = rows
        state.selected = try ChatConversation(target: ChatTarget(sessionID: "s1"), title: nil)
        let ids = state.titleCandidates(newerPageFirst: true)
        #expect(ids.count == 100)
        #expect(Array(ids.prefix(3)) == ["s1", "s130", "s129"])
        #expect(!ids.contains("manual") && !ids.contains("ready"))
        try state.applyTitles([title("s1")])
        #expect(state.conversations.items.count == rows.count)
    }

    private func prepared(_ body: (HistoryHarness) async throws -> Void) async throws {
        try await withHistory { h in
            try await h.login(); try await h.conversations().succeed([historySummary(1, "a")])
            try await awaitHistory { h.model.state.conversations.loaded }
            try await body(h)
        }
    }
}
