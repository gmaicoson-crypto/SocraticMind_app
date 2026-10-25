import Foundation
@testable import MindCore
import Testing

@MainActor
struct ChatAvatarModelTests {
    private var preset: ChatAvatarResource {
        get throws { try ChatAvatarResource(ChatAvatarResource.presets(for: .normal)[1]) }
    }

    @Test func presetSupportsEmptyConversationAndRejectsStalePicker() async throws {
        try await withAvatar { h in
            try await h.login()
            let old = try h.picker()
            h.model.dismiss()
            let target = try ChatTarget(sessionID: "new-local")
            h.base.history.model.openConversation(target)
            try await h.base.history.messages().succeed([])
            h.base.turn.select(target)
            let picker = try h.picker()
            try h.model.selectPreset(preset, picker: old)
            h.model.selectPreset(.fallback(for: .socratic), picker: picker)
            #expect(await h.gateway.count == 0)
            try h.model.selectPreset(preset, picker: picker)
            let call = try await h.next()
            #expect(call.kind == "delete"); #expect(call.sessionID == "new-local")
            #expect(try await h.store.read(ownerID: 1)["new-local"] == preset)
            await call.finish(.success(nil)); try await h.idle()
            #expect(try h.model.state.resource(for: target) == preset)
        }
    }

    @Test func uploadSnapshotsDataAndHoldsSharedMutationGate() async throws {
        try await withAvatar { h in
            try await h.login()
            let picker = try h.picker()
            var data = Data([1, 2, 3])
            h.model.upload(data, format: .png, picker: picker); data[0] = 9
            h.model.upload(data, format: .png, picker: picker)
            let call = try await h.next()
            #expect(call.data == Data([1, 2, 3])); #expect(!h.base.turn.state.editable)
            h.base.turn.send(style: "标准"); h.base.model.deleteSession("main")
            #expect(h.base.model.state.dialog == nil); #expect(await h.base.turnGateway.streamCount == 0)
            try await call.finish(.success(uploadedAvatar())); try await h.idle()
            #expect(try await h.store.read(ownerID: 1)["main"] == uploadedAvatar())
            #expect(await h.gateway.count == 1); #expect(h.base.turn.state.editable)
            #expect(h.base.turn.state.draft == "未发送的草稿")
        }
    }

    @Test func failedSaveRetainsPreviewAndRetriesWithoutAnotherUpload() async throws {
        try await withAvatar { h in
            try await h.login()
            let picker = try h.picker()
            await h.store.configure(writeFailure: true)
            h.model.upload(Data([1]), format: .png, picker: picker)
            try await h.next().finish(.success(uploadedAvatar())); try await h.idle()
            #expect(h.model.state.pendingSave != nil)
            #expect(try h.model.state.resource(for: picker.target) == uploadedAvatar())
            h.model.dismiss(); h.model.open(picker.target)
            #expect(h.model.state.picker == nil)
            await h.store.configure(); h.model.retrySave(); try await h.idle()
            #expect(h.model.state.pendingSave == nil)
            #expect(try await h.store.read(ownerID: 1)["main"] == uploadedAvatar())
            #expect(await h.gateway.count == 1)
        }
    }

    @Test func retryRecognizesWriteCompletedBeforeReadbackFailed() async throws {
        try await withAvatar { h in
            try await h.login(); await h.store.configure(failAfterWrite: true)
            try h.model.upload(Data([1]), format: .png, picker: h.picker())
            try await h.next().finish(.success(uploadedAvatar())); try await h.idle()
            #expect(h.model.state.pendingSave != nil)
            h.model.retrySave(); try await h.idle()
            #expect(h.model.state.pendingSave == nil)
            #expect(await h.store.writes == 1); #expect(await h.gateway.count == 1)
        }
    }

    @Test func presetCleanupFollowsSavingAndFailureDoesNotRollBackSelection() async throws {
        try await withAvatar { h in
            try await h.login(); await h.store.configure(writeFailure: true)
            try h.model.selectPreset(preset, picker: h.picker()); try await h.idle()
            #expect(await h.gateway.count == 0)
            await h.store.configure(); h.model.retrySave()
            let cleanup = try await h.next()
            #expect(try await h.store.read(ownerID: 1)["main"] == preset)
            await cleanup.finish(.failure(SessionTestError.storage)); try await h.idle()
            #expect(try h.model.state.choices?["main"] == preset)
            #expect(h.model.state.pendingSave == nil); #expect(h.model.state.notice?.contains("已保存") == true)
            try h.model.selectPreset(nil, picker: h.picker())
            try await h.next().finish(.success(nil)); try await h.idle()
            #expect(try await h.store.read(ownerID: 1)["main"] == nil)
        }
    }

    @Test func corruptStorageBlocksChangesUntilExplicitReload() async throws {
        try await withAvatar { h in
            await h.store.configure(readFailure: true); try await h.login()
            try h.model.open(#require(h.base.turn.state.target))
            #expect(!h.model.state.loaded); #expect(h.model.state.picker == nil)
            #expect(await h.store.writes == 0)
            await h.store.configure(); h.model.reload(); try await h.idle()
            #expect(h.model.state.loaded)
        }
    }

    @Test func unknownUploadIsNotReplayedOrTreatedAsSuccess() async throws {
        try await withAvatar { h in
            try await h.login(); try h.model.upload(Data([1]), format: .png, picker: h.picker())
            try await h.next().finish(.failure(SessionTestError.storage)); try await h.idle()
            #expect(h.model.state.notice?.contains("未确认") == true)
            #expect(await h.gateway.count == 1); #expect(await h.store.writes == 0)
            h.model.retrySave(); #expect(await h.gateway.count == 1)
        }
    }

    @Test func oldUploadCannotWriteAfterAccountChangeOrReleaseNewLease() async throws {
        try await withAvatar { h in
            try await h.login(); try h.model.upload(Data([1]), format: .png, picker: h.picker())
            let old = try await h.next()
            try await h.login(2); try h.model.upload(Data([2]), format: .png, picker: h.picker())
            let newer = try await h.next()
            try await old.finish(.success(uploadedAvatar()))
            try await awaitHistory { await old.completed }; await Task.yield()
            #expect(h.model.state.busy); #expect(!h.base.turn.state.editable)
            #expect(await h.store.writes == 0)
            try await newer.finish(.success(uploadedAvatar(2))); try await h.idle()
            #expect(try await h.store.read(ownerID: 1).isEmpty)
            #expect(try await h.store.read(ownerID: 2)["main"] == uploadedAvatar(2))
        }
    }

    @Test func currentUnauthorizedClearsStateAndLateUnauthorizedCannotExpireNextLogin() async throws {
        try await withAvatar { h in
            try await h.login(); try h.model.upload(Data([1]), format: .png, picker: h.picker())
            try await h.next().finish(.failure(sessionHTTPFailure(401)))
            try await awaitHistory { h.model.state.account == nil }
            #expect(await h.base.session.state == .signedOut(expired: true))
            try await h.login(); try h.model.upload(Data([1]), format: .png, picker: h.picker())
            let old = try await h.next()
            try await h.login()
            await old.finish(.failure(sessionHTTPFailure(401)))
            try await awaitHistory { await old.completed }; await Task.yield()
            #expect(h.model.state.account != nil)
            guard case .signedIn = await h.base.session.state else { Issue.record("New login expired"); return }
        }
    }

    @Test func conflictingSavePreservesOtherSelectionAndDiscardReloadsIt() async throws {
        try await withAvatar { h in
            try await h.login()
            let picker = try h.picker(), other = ChatAvatarResource.fallback(for: .normal)
            try await h.store.seed(1, "main", other)
            try h.model.selectPreset(preset, picker: picker); try await h.idle()
            #expect(h.model.state.pendingSave != nil)
            #expect(try await h.store.read(ownerID: 1)["main"] == other)
            #expect(await h.gateway.count == 0)
            h.model.discardPendingSave(); try await h.idle()
            #expect(h.model.state.pendingSave == nil); #expect(h.model.state.choices?["main"] == other)
        }
    }

    @Test func confirmedDeletionOnlyRemovesItsSelectionAndCleanupFailureKeepsDeletionSuccessful() async throws {
        for fail in [false, true] {
            try await withAvatar { h in
                try await h.store.seed(1, "main", preset); try await h.store.seed(1, "other", preset)
                try await h.login(); await h.store.configure(writeFailure: fail)
                h.base.model.deleteSession("main"); h.base.model.confirm()
                try await h.base.next().finish(.success(nil))
                try await awaitHistory { !h.base.model.state.busy }
                #expect(h.base.history.model.state.selected == nil); #expect(h.base.turn.state.editable)
                #expect(h.model.state.choices?["main"] == nil)
                #expect(try h.model.state.choices?["other"] == preset)
                #expect(try await h.store.read(ownerID: 1)["main"] == (fail ? preset : nil))
                #expect((h.base.model.state.notice != nil) == fail)
            }
        }
    }

    @Test func selectionsSurviveLogoutAndKeepVisuallyEqualIdentifiersSeparate() async throws {
        try await withAvatar { h in
            try await h.store.seed(1, "café", preset)
            try await h.store.seed(1, "cafe\u{0301}", .fallback(for: .normal))
            try await h.login()
            #expect(try h.model.state.resource(for: ChatTarget(sessionID: "café")) == preset)
            #expect(try h.model.state.resource(for: ChatTarget(sessionID: "cafe\u{0301}")) == .fallback(for: .normal))
            try await h.login(2); #expect(h.model.state.choices?.isEmpty == true)
            try await h.login(); #expect(h.model.state.choices?.count == 2)
        }
    }

    @Test func lateInitialReadCannotLeakPreviousAccountChoices() async throws {
        try await withAvatar { h in
            try await h.base.login(); try await h.store.seed(1, "main", preset)
            let gate = AvatarWrite("read", sessionID: "main")
            await h.store.gateReads(gate)
            await h.model.bindAccount(h.base.session.state)
            try await awaitHistory { await h.store.reads == 1 }
            h.model.clear(); await h.store.gateReads(nil)
            try await h.login(2)
            await gate.finish(.success(nil)); await Task.yield()
            #expect(h.model.state.account?.userID == 2); #expect(h.model.state.choices?.isEmpty == true)
        }
    }

    @Test func deletionFencesPendingInitialAvatarRead() async throws {
        try await withAvatar { h in
            try await h.base.login(); try await h.store.seed(1, "main", preset)
            let gate = AvatarWrite("read", sessionID: "main")
            await h.store.gateReads(gate); await h.model.bindAccount(h.base.session.state)
            try await awaitHistory { await h.store.reads == 1 }
            await h.store.gateReads(nil)
            h.base.model.deleteSession("main"); h.base.model.confirm()
            try await h.base.next().finish(.success(nil))
            try await awaitHistory { !h.base.model.state.busy }
            await gate.finish(.success(nil)); try await awaitHistory { await gate.completed }; await Task.yield()
            #expect(h.model.state.loaded); #expect(!h.model.state.busy)
            #expect(h.model.state.choices?.isEmpty == true)
            #expect(try await h.store.read(ownerID: 1).isEmpty)
        }
    }

    @Test func deletionRechecksGenerationAfterAwaitingAnOldAccountSnapshot() async throws {
        try await withAvatar(controlAccountSnapshots: true) { h in
            try await h.store.seed(1, "main", preset)
            try await h.store.seed(2, "other", .fallback(for: .socratic))
            try await h.login()
            let account = try #require(h.model.state.account)
            let lease = try #require(h.base.turn.reserveHistoryMutation(account))
            let gate = AvatarWrite("account", sessionID: "main"), reader = h.accountReader
            defer { Task { await gate.finish(.success(nil)) } }
            await h.store.onWrite { await reader.holdNext(gate) }
            let old = Task { await h.model.forgetDeletedSession(account: account, sessionID: "main") }
            try await awaitHistory { await reader.captured }
            try await h.login(2)
            try h.model.upload(Data([2]), format: .png, picker: h.picker())
            let upload = try await h.next()
            await gate.finish(.success(nil))
            #expect(await old.value == nil)
            #expect(h.model.state.account?.userID == 2)
            #expect(h.model.state.busy); #expect(!h.base.turn.state.editable)
            #expect(h.model.state.choices?["other"] == .fallback(for: .socratic))
            h.base.turn.releaseHistoryMutation(lease)
            #expect(!h.base.turn.state.editable)
            try await upload.finish(.success(uploadedAvatar(2))); try await h.idle()
        }
    }

    @Test func invalidInputAndForeignResponseNeverBecomeASelection() async throws {
        try await withAvatar { h in
            try await h.login()
            let picker = try h.picker()
            h.model.upload(Data(), format: .png, picker: picker)
            #expect(await h.gateway.count == 0)
            h.model.upload(Data([1]), format: .png, picker: picker)
            try await h.next().finish(.success(uploadedAvatar(2))); try await h.idle()
            #expect(await h.store.writes == 0); #expect(h.model.state.pendingSave == nil)
        }
    }
}
