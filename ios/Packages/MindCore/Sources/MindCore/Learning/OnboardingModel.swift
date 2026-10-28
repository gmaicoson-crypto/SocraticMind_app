import Combine
import Foundation

/// Owns the pending transaction; local task cancellation never asserts server cancellation.
@MainActor
public final class OnboardingModel: ObservableObject {
    @Published public private(set) var state = OnboardingState()
    private let session: SessionStore
    private let gateway: any OnboardingGateway
    private let journal: any OnboardingJournal
    private let newID: @Sendable () -> OnboardingID
    private let pollDelays: [UInt64]
    private var task: Task<Void, Never>?
    private var ticket: UInt64 = 0
    private var closed = false

    public init(session: SessionStore, gateway: any OnboardingGateway, journal: any OnboardingJournal,
                newID: @escaping @Sendable () -> OnboardingID = { OnboardingID.create() },
                pollDelays: [UInt64] = [500_000_000, 1_000_000_000, 2_000_000_000])
    {
        self.session = session; self.gateway = gateway; self.journal = journal
        self.newID = newID; self.pollDelays = pollDelays
    }

    public func bindAccount(_ value: SessionState) async {
        let actual = await session.state
        let account = OnboardingAccount.from(value)
        guard !closed, account == OnboardingAccount.from(actual), account != state.account else { return }
        clear()
        guard let account else { return }
        state.account = account
        launch { try await self.restore($0) }
    }

    public func close() {
        closed = true; clear()
    }

    public func acknowledge(_ receipt: OnboardingResult) {
        if current, state.receipt == receipt {
            state.receipt = nil
        }
    }

    public func start(form: OnboardingForm, model: String? = nil) throws {
        guard current, state.canStart else { return }
        if let model {
            try learningText(model, maximum: 100)
        }
        guard let account = state.account else { return }
        let pending = try PendingOnboarding(ownerID: account.ownerID, runID: newID(), confirmationID: newID())
        state.pending = pending; state.run = nil
        launch { operation in
            try await self.requireCurrent(operation)
            try await self.storage { try await self.journal.save(pending) }
            let run = try await self.request(operation) { try await self.gateway.start(
                token: $0,
                id: pending.runID,
                form: form,
                model: model
            ) }
            try await self.settle(operation, pending: pending, initial: run)
        }
    }

    public func refresh() {
        guard current, !state.busy else { return }
        if let pending = state.pending, let terminal = state.run,
           terminal.status == .completed || terminal.status == .cancelled
        {
            // Removal can succeed before verification fails. Retain the known completion
            // while retrying cleanup, even when the record is already absent.
            launch { try await self.settle($0, pending: pending, initial: terminal) }
        } else {
            launch { try await self.restore($0) }
        }
    }

    public func answer(_ text: String) throws {
        guard current, state.canAnswer, let run = state.run, let step = run.step else { return }
        try learningText(text, maximum: 5000)
        mutate { try await self.gateway.answer(
            token: $0,
            id: run.id,
            version: run.version,
            stepID: step.id,
            answer: text
        ) }
    }

    public func revise(goal: String, minutes: Int, targetDate: String?, timezone: String) throws {
        guard current, state.canRevise, let run = state.run else { return }
        try learningText(goal, maximum: 300); try learningText(timezone, maximum: 100)
        guard (5 ... 240).contains(minutes) else { throw OnboardingFailure.invalidInput }
        if let targetDate {
            try learningDate(targetDate)
        }
        mutate { try await self.gateway.revise(token: $0, id: run.id, version: run.version, goal: goal,
                                               dailyMinutes: minutes, targetDate: targetDate, timezone: timezone) }
    }

    public func confirm() {
        guard current, state.canConfirm, let run = state.run, let pending = state.pending else { return }
        mutate { try await self.gateway.confirm(
            token: $0,
            id: run.id,
            version: run.version,
            requestID: pending.confirmationID.value
        ) }
    }

    public func retry() {
        guard current, state.canRetry, let run = state.run else { return }
        mutate { try await self.gateway.retry(token: $0, id: run.id, version: run.version) }
    }

    public func cancel() {
        guard current, state.canCancel, let pending = state.pending else { return }
        launch { operation in
            // A previous atomic save can outlive local task cancellation; verify it before cancel IO.
            try await self.requireCurrent(operation)
            try await self.storage { try await self.journal.save(pending) }
            let run = try await self.request(operation) { try await self.gateway.cancel(token: $0, id: pending.runID) }
            try await self.settle(operation, pending: pending, initial: run)
        }
    }

    private func mutate(_ block: @escaping @Sendable (String) async throws -> OnboardingRun) {
        guard let pending = state.pending else { return }
        launch { operation in
            let run = try await self.request(operation, block)
            try await self.settle(operation, pending: pending, initial: run)
        }
    }

    private func restore(_ operation: Operation) async throws {
        let pending = try await storage { try await self.journal.read(ownerID: operation.account.ownerID) }
        try await requireCurrent(operation)
        state.ready = true; state.pending = pending; state.run = nil; state.needsRefresh = pending != nil
        if let pending {
            let run = try await request(operation) { try await self.gateway.read(token: $0, id: pending.runID) }
            try await settle(operation, pending: pending, initial: run)
        }
    }

    private func settle(_ operation: Operation, pending: PendingOnboarding, initial: OnboardingRun) async throws {
        var run = initial, polls = 0
        while true {
            try await requireCurrent(operation)
            guard run.id == pending.runID else { throw OnboardingFailure.invalidResponse }
            state.run = run; state.needsRefresh = false; state.issue = nil
            if run.status == .completed || run.status == .cancelled {
                if run.status == .completed, run.result == nil {
                    throw OnboardingFailure.invalidResponse
                }
                let result = run.status == .completed ? run.result : nil
                try await storage { try await self.journal.clear(pending) }
                try await requireCurrent(operation)
                state.pending = nil; state.receipt = result
                return
            }
            if !run.processing || polls >= pollDelays.count {
                return
            }
            try await Task.sleep(nanoseconds: pollDelays[polls]); polls += 1
            run = try await request(operation) { try await self.gateway.read(token: $0, id: pending.runID) }
        }
    }

    private func request(
        _ operation: Operation,
        _ block: @escaping @Sendable (String) async throws -> OnboardingRun
    ) async throws -> OnboardingRun {
        try await session.authenticated { token in
            try await self.requireCurrent(operation)
            return try await block(token)
        }
    }

    private func launch(_ block: @escaping @MainActor (Operation) async throws -> Void) {
        task?.cancel(); ticket += 1
        guard let account = state.account else { return }
        let operation = Operation(ticket: ticket, account: account)
        state.busy = true; state.issue = nil
        task = Task {
            defer {
                if valid(operation) {
                    state.busy = false
                }
            }
            do { try await block(operation) }
            catch is CancellationError { return }
            catch {
                guard valid(operation) else { return }
                if error is StorageFailure {
                    state.issue = .storage
                } else if let error = error as? HTTPFailure, error.status == 404 {
                    state.issue = .notFound
                } else if let error = error as? HTTPFailure, error.status == 409 {
                    state.issue = .conflict
                } else {
                    state.issue = .request
                }
                state.needsRefresh = true
            }
        }
    }

    private var current: Bool {
        !closed && state.account != nil
    }

    private func valid(_ operation: Operation) -> Bool {
        current && operation.ticket == ticket && operation
            .account == state.account
    }

    private func requireCurrent(_ operation: Operation) async throws {
        let actual = await session.state
        guard valid(operation), operation.account == OnboardingAccount.from(actual) else { throw CancellationError() }
    }

    private func clear() {
        ticket += 1; task?.cancel(); task = nil; state = OnboardingState()
    }

    private struct Operation: Sendable { let ticket: UInt64; let account: OnboardingAccount }
    private struct StorageFailure: Error {}
    private func storage<T>(_ block: () async throws -> T) async throws -> T {
        do { return try await block() }
        catch is CancellationError { throw CancellationError() }
        catch { throw StorageFailure() }
    }
}
