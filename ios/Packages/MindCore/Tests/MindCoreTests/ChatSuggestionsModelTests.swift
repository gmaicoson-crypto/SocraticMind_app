import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatSuggestionsModelTests {
    @Test
    func newConversationUsesLocalStartersAndExplicitRefreshAvoidsAllShown() async throws {
        try await withSuggestions { h in
            try await h.replace([]); h.model.setActive(true)
            try await awaitHistory { h.model.state.enabled }
            let shown = h.model.state.items, expected = try suggestionFixture().defaults["normal_new"]
            #expect(try shown == Array(#require(expected).prefix(12)))
            #expect(await h.gateway.count == 0)
            h.model.refresh(); let read = try await h.gateway.next()
            #expect(read.exclude == shown)
            try await read.finish(.success(ChatSuggestions(items: shown, source: .fallback)))
            try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.items.allSatisfy { !shown.contains($0) })
            #expect(h.model.state.source == .local)
        }
    }

    @Test
    func currentContextLoadsOnceAndRevisitUsesMemoryCache() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); try await h.gateway.next().succeed(["上下文追问"])
            try await awaitHistory { !h.model.state.loading }
            h.base.turn.edit("草稿变化"); await Task.yield()
            #expect(await h.gateway.count == 1)
            try await h.select("other"); try await h.gateway.next().succeed(["另一会话"])
            try await awaitHistory { !h.model.state.loading }
            try await h.select("main")
            try await awaitHistory { h.model.state.items == ["上下文追问"] }
            #expect(await h.gateway.count == 2)
        }
    }

    @Test
    func contextChangesRejectLateResultsAndSameTextStaleTaps() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); let old = try await h.gateway.next()
            let context = try #require(h.model.state.context), text = try #require(h.model.state.items.first)
            try await h.select("other"); let fresh = try await h.gateway.next()
            await h.model.choose(text, context: context, style: "标准")
            #expect(h.base.turn.state.draft.isEmpty && h.base.turn.state.pending == nil)
            try await old.succeed(["旧会话秘密"]); try await awaitHistory { await old.completed }
            #expect(!h.model.state.items.contains("旧会话秘密"))
            try await fresh.succeed(["新会话建议"]); try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.items == ["新会话建议"])
        }
    }

    @Test
    func sameMessageIdentityWithChangedContentInvalidatesContext() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); try await h.gateway.next().succeed(["旧内容建议"])
            try await awaitHistory { !h.model.state.loading }
            let before = try #require(h.model.state.context)
            try await h.replace([suggestionMessage(104, "main", text: "更新后的合成话题")])
            let read = try await h.gateway.next()
            #expect(before.version != h.model.state.context?.version)
            try await read.succeed(["新内容建议"]); try await awaitHistory { !h.model.state.loading }
        }
    }

    @Test
    func visibilityAndModelChangesCancelAndRejectLateReads() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); let old = try await h.gateway.next()
            h.model.setActive(false); try await old.succeed(["后台迟到"])
            try await awaitHistory { await old.completed }
            #expect(!h.model.state.enabled && !h.model.state.items.contains("后台迟到"))
            h.model.setActive(true); let resumed = try await h.gateway.next()
            h.model.setModel("second-model"); let changed = try await h.gateway.next()
            #expect(changed.model == "second-model")
            try await resumed.succeed(["旧模型"]); try await changed.succeed(["新模型"])
            try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.items == ["新模型"])
        }
    }

    @Test
    func failureShowsLocalFollowupsAndRetryIsExplicit() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); try await h.gateway.next().finish(.failure(SessionTestError.offline))
            try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.source == .local)
            #expect(h.model.state.notice?.contains("暂不可用") == true)
            #expect(h.model.state.items.first?.contains("刚才") == true)
            h.base.turn.edit("typing"); await Task.yield(); #expect(await h.gateway.count == 1)
            h.model.refresh(); try await h.gateway.next().succeed(["恢复后的建议"])
            try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.source == .ai)
        }
    }

    @Test
    func suggestedSendConfirmsDraftAndReusesOneDurableRequestDespiteAlertDismissal() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); try await h.gateway.next().succeed(["建议文本"])
            try await awaitHistory { !h.model.state.loading }
            h.base.turn.edit("保留的草稿"); let context = try #require(h.model.state.context)
            await h.model.choose("建议文本", context: context, style: "标准")
            #expect(h.base.turn.state.draft == "保留的草稿" && h.base.turn.state.pending == nil)
            h.model.cancelChoice(); #expect(h.model.state.choice == nil)
            await h.model.choose("建议文本", context: context, style: "标准")
            h.model.confirmChoice(style: "标准"); h.model.cancelChoice(); h.model.confirmChoice(style: "标准")
            let stream = try await nextTurn { await h.base.turnGateway.popStream() }
            #expect(stream.request.input == "建议文本" && stream.request.pending == stream.saved)
            await h.model.choose("建议文本", context: context, style: "标准")
            #expect(await h.base.turnGateway.streamCount == 0)
        }
    }

    @Test
    func refreshAfterCanceledDraftConfirmationExcludesDisplayedSuggestions() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); let old = try await h.gateway.next()
            let shown = h.model.state.items, context = try #require(h.model.state.context)
            h.base.turn.edit("保留的草稿")
            try await h.model.choose(#require(shown.first), context: context, style: "标准")
            h.model.cancelChoice(); h.model.refresh()
            let fresh = try await h.gateway.next()
            #expect(fresh.exclude == shown)
            try await old.succeed(["取消前的建议"])
            try await fresh.succeed(["新一批建议"])
            try await awaitHistory { !h.model.state.loading }
            #expect(h.model.state.items == ["新一批建议"])
            #expect(h.base.turn.state.draft == "保留的草稿" && h.base.turn.state.pending == nil)
        }
    }

    @Test
    func editedDraftsAndMutationsRejectPendingOrStaleSends() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); try await h.gateway.next().succeed(["建议"])
            try await awaitHistory { !h.model.state.loading }
            let context = try #require(h.model.state.context)
            h.base.turn.edit("草稿A"); await h.model.choose("建议", context: context, style: "标准")
            h.base.turn.edit("草稿B"); h.model.confirmChoice(style: "标准"); await Task.yield()
            #expect(h.base.turn.state.draft == "草稿B" && h.base.turn.state.pending == nil)
            h.base.model.deleteSession("main"); h.base.model.confirm(); _ = try await h.base.next()
            await h.model.choose("建议", context: context, style: "标准")
            #expect(h.base.turn.state.draft == "草稿B" && h.base.turn.state.pending == nil)
        }
    }

    @Test(arguments: [false, true])
    func oldAccountSuccessOr401CannotAffectNewLogin(unauthorized: Bool) async throws {
        try await withSuggestions { h in
            h.model.setActive(true); let old = try await h.gateway.next()
            try await h.login(2); let fresh = try await h.gateway.next()
            #expect(fresh.token == "synthetic-token-2")
            if unauthorized {
                await old.finish(.failure(sessionHTTPFailure(401)))
            } else {
                try await old.succeed(["账号一"])
            }
            try await awaitHistory { await old.completed }
            try await fresh.succeed(["账号二"]); try await awaitHistory { !h.model.state.loading }
            #expect(await HistoryAccount.from(h.base.session.state)?.userID == 2)
            #expect(h.model.state.items == ["账号二"])
        }
    }

    @Test
    func current401ClearsBeforeHostObservation() async throws {
        try await withSuggestions { h in
            h.model.setActive(true); try await h.gateway.next().finish(.failure(sessionHTTPFailure(401)))
            try await awaitHistory { h.model.state.context == nil }
            h.model.setActive(true)
            #expect(h.model.state.items.isEmpty && !h.model.state.enabled)
            #expect(await h.base.session.state == .signedOut(expired: true))
        }
    }

    @Test
    func cacheEvictsByEntryAndByteBudgetsAndDoesNotCacheFallback() async throws {
        try await withSuggestions { h in
            let context = try #require(ChatSuggestionContext.from(h.base.history.model.state, h.base.turn.state))
            func key(_ value: String) -> ChatSuggestionContext {
                ChatSuggestionContext(account: context.account, target: context.target, version: value,
                                      hasConversation: context.hasConversation, model: context.model)
            }
            var cache = ChatSuggestionsCache()
            for i in 0 ..< 31 {
                try cache.put(key(String(i)), ChatSuggestions(items: ["建议\(i)"], source: .ai))
            }
            #expect(cache.count == 30 && cache.get(key("0")) == nil)
            cache.clear()
            for i in 0 ..< 15 {
                try cache.put(
                    key(String(i)),
                    ChatSuggestions(items: [String(repeating: "🙂", count: 1200)], source: .ai)
                )
            }
            #expect(cache.count == 13 && cache.get(key("1")) == nil)
            try cache.put(context, ChatSuggestions(items: ["备用"], source: .fallback))
            #expect(cache.get(context) == nil)
        }
    }
}
