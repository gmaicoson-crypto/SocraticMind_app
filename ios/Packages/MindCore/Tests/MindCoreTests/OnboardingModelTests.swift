import Foundation
@testable import MindCore
import Testing

@MainActor
struct OnboardingModelTests {
    @Test
    func persistBeforeStartAndCarryObservedVersionsToOneCompletionReceipt() async throws {
        let h = try LearningHarness()
        do {
            try await h.login(); try await h.ready(); try h.model.start(form: learningForm())
            let start = try await h.next(), saved = try #require(start.saved)
            #expect(start.id == saved.runID)
            try h.model.start(form: learningForm()); #expect(await h.gateway.observed.count == 1)
            try await h.finish(start, "diagnosing"); #expect(h.model.state.canAnswer)
            try h.model.answer("答案"); let answer = try await h.next()
            #expect(answer.version == h.model.state.run?.version)
            try await h.finish(answer, "preview"); try h.model.revise(
                goal: "调整",
                minutes: 20,
                targetDate: nil,
                timezone: "Asia/Shanghai"
            )
            let revise = try await h.next(); #expect(revise.version == h.model.state.run?.version)
            try await h.finish(revise, "edited"); h.model.confirm(); h.model.confirm()
            let confirm = try await h.next()
            #expect(confirm.confirmation == saved.confirmationID.value && confirm.version == h.model.state.run?.version)
            try await h.finish(confirm, "completed")
            let receipt = try #require(h.model.state.receipt)
            #expect(try await h.journal.read(ownerID: 1) == nil)
            #expect(!h.model.state.canStart)
            #expect(await h.gateway.observed.filter { $0.kind == "confirm" }.count == 1)
            h.model.acknowledge(receipt); #expect(h.model.state.canStart)
        } catch { await h.close(); throw error }
        await h.close()
    }

    @Test
    func unknownCreationAnd404RetainIdentityUntilSafeCancellation() async throws {
        let h = try LearningHarness()
        do {
            try await h.login(); try await h.ready(); try h.model.start(form: learningForm())
            let start = try await h.next()
            await start.finish(.failure(HTTPFailure(status: 503, code: nil, userMessage: "synthetic", retryable: true)))
            try await awaitHistory { !h.model.state.busy }
            try h.model.start(form: learningForm()); h.model.confirm(); #expect(await h.gateway.observed.count == 1)
            h.model.refresh(); let read = try await h.next(); #expect(read.id == start.id)
            await read.finish(.failure(HTTPFailure(status: 404, code: nil, userMessage: "synthetic", retryable: false)))
            try await awaitHistory { h.model.state.issue == .notFound }
            #expect(try await h.journal.read(ownerID: 1) != nil); #expect(!h.model.state.canStart)
            h.model.cancel(); let cancel = try await h.next(); #expect(cancel.kind == "cancel" && cancel.id == start.id)
            try await h.finish(cancel, "cancelled")
            #expect(try await h.journal.read(ownerID: 1) == nil); #expect(h.model.state.canStart)
        } catch { await h.close(); throw error }
        await h.close()
    }

    @Test
    func cancelSupersedesLocalRequestAndRejectsLateSuccess() async throws {
        let h = try LearningHarness()
        do {
            try await h.login(); try await h.ready(); try h.model.start(form: learningForm())
            let start = try await h.next()
            h.model.cancel(); try await h.finish(h.next(), "cancelled")
            try await start.finish(.success(learningRun("completed", id: start.id)))
            try await awaitHistory { await start.completed }
            h.model.refresh(); try await awaitHistory { !h.model.state.busy }
            #expect(h.model.state.receipt == nil && h.model.state.canStart)
        } catch { await h.close(); throw error }
        await h.close()
    }

    @Test
    func accountSwitchFencesLate401AndRestoresOnlyOriginalOwner() async throws {
        let h = try LearningHarness()
        do {
            try await h.login(); try await h.ready(); try h.model.start(form: learningForm())
            let old = try await h.next(), prior = await h.session.state
            try await h.login(2); try await h.ready(); await h.model.bindAccount(prior)
            await old.finish(.failure(HTTPFailure(status: 401, code: nil, userMessage: "late", retryable: false)))
            try await awaitHistory { await old.completed }
            #expect(h.model.state.account?.ownerID == 2)
            guard case let .signedIn(user, _) = await h.session.state
            else { Issue.record("New account was lost"); await h.close(); return }
            #expect(user.id == 2)
            try await h.login(1); let read = try await h.next(); #expect(read.kind == "read" && read.id == old.id)
            try await h.finish(read, "preview"); h.model.confirm(); let confirm = try await h.next()
            #expect(confirm.confirmation == old.saved?.confirmationID.value)
            try await h.finish(confirm, "completed")
        } catch { await h.close(); throw error }
        await h.close()
    }

    @Test
    func failedSaveNeverPostsAndTerminalClearFailureRetainsRecovery() async throws {
        let h = try LearningHarness()
        do {
            try await h.login(); try await h.ready(); await h.journal.failures(save: true)
            try h.model.start(form: learningForm())
            try await awaitHistory { h.model.state.issue == .storage }
            #expect(await h.gateway.observed.isEmpty); #expect(!h.model.state.canStart)
            await h.journal.failures(); h.model.refresh(); let read = try await h.next()
            await h.journal.failures(clear: true); try await h.finish(read, "completed")
            #expect(h.model.state.pending != nil && h.model.state.receipt == nil && h.model.state.issue == .storage)
            await h.journal.failures(); h.model.refresh(); try await awaitHistory { !h.model.state.busy }
            #expect(h.model.state.receipt != nil); #expect(try await h.journal.read(ownerID: 1) == nil)
        } catch { await h.close(); throw error }
        await h.close()
    }

    @Test
    func boundedPollingAndConflictRequireReadBeforeAnotherMutation() async throws {
        let h = try LearningHarness(polls: [1_000_000, 1_000_000])
        do {
            try await h.login(); try await h.ready(); try h.model.start(form: learningForm())
            for _ in 0 ..< 3 {
                let call = try await h.next(); try await call.finish(.success(learningRun(
                    "processing",
                    id: call.id
                )))
            }
            try await awaitHistory { !h.model.state.busy }
            #expect(await h.gateway.observed.count == 3); #expect(!h.model.state.canConfirm)
            h.model.refresh(); try await h.finish(h.next(), "preview"); h.model.confirm()
            let confirm = try await h.next()
            await confirm.finish(.failure(HTTPFailure(
                status: 409,
                code: "AGENT_STATE_CONFLICT",
                userMessage: "synthetic",
                retryable: false
            )))
            try await awaitHistory { !h.model.state.busy }; h.model.confirm(); h.model.retry()
            #expect(await h.gateway.observed.filter { $0.kind == "confirm" }.count == 1)
            #expect(h.model.state.needsRefresh)
            h.model.refresh(); try await h.finish(h.next(), "failed"); #expect(h.model.state.canRetry)
            h.model.retry(); let retry = try await h.next(); #expect(retry.version == h.model.state.run?.version)
            try await h.finish(retry, "diagnosing")
        } catch { await h.close(); throw error }
        await h.close()
    }

    @Test
    func readFailureBlocksNewWorkAndPostDeleteErrorPreservesCompletion() async throws {
        let h = try LearningHarness()
        do {
            await h.journal.failures(read: true); try await h.login()
            try await awaitHistory { h.model.state.issue == .storage }
            try h.model.start(form: learningForm()); #expect(await h.gateway.observed.isEmpty)
            await h.journal.failures(); h.model.refresh(); try await h.ready(); try h.model.start(form: learningForm())
            try await h.finish(h.next(), "preview")
            await h.journal.failures(afterClear: true); h.model.confirm(); try await h.finish(h.next(), "completed")
            #expect(try await h.journal.read(ownerID: 1) == nil); #expect(h.model.state.pending != nil)
            #expect(h.model.state.issue == .storage)
            let requests = await h.gateway.observed.count
            await h.journal.failures(); h.model.refresh(); try await awaitHistory { !h.model.state.busy }
            #expect(h.model.state.receipt != nil && h.model.state.pending == nil)
            #expect(await h.gateway.observed.count == requests)
        } catch { await h.close(); throw error }
        await h.close()
    }

    @Test
    func failedRereadAndWrongResponseIdentityNeverAllowStartingOver() async throws {
        let h = try LearningHarness()
        do {
            try await h.login(); try await h.ready(); await h.journal.failures(read: true); h.model.refresh()
            try await awaitHistory { !h.model.state.busy }; #expect(!h.model.state.canStart)
            try h.model.start(form: learningForm()); #expect(await h.gateway.observed.isEmpty)
            await h.journal.failures(); h.model.refresh(); try await h.ready(); try h.model.start(form: learningForm())
            let start = try await h.next()
            try await start.finish(.success(learningRun("completed", id: .create())))
            try await awaitHistory { !h.model.state.busy }
            #expect(h.model.state.issue == .request && h.model.state.receipt == nil)
            #expect(h.model.state.pending?.runID == start.id)
            h.model.refresh(); let read = try await h.next(); #expect(read.id == start.id)
            try await h.finish(read, "preview"); #expect(h.model.state.canConfirm)
        } catch { await h.close(); throw error }
        await h.close()
    }
}
