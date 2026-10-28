import Foundation
@testable import MindCore

func learningForm() throws
    -> OnboardingForm
{
    try LearningRow(onboardingFixture("onboarding-runs.json").optional("request")).form()
}

func learningRun(_ name: String, id: OnboardingID) throws -> OnboardingRun {
    var row = try LearningRow(LearningRow(onboardingFixture("onboarding-runs.json").optional("responses"))
        .optional(name)).values
    row["run_id"] = id.value
    return try decodeRun(row, id: id)
}

actor MemoryOnboardingJournal: OnboardingJournal {
    private var records: [Int64: PendingOnboarding] = [:]
    private var failRead = false, failSave = false, failClear = false, failAfterClear = false
    func failures(read: Bool = false, save: Bool = false, clear: Bool = false, afterClear: Bool = false) {
        failRead = read; failSave = save; failClear = clear; failAfterClear = afterClear
    }

    func read(ownerID: Int64) throws -> PendingOnboarding? {
        if failRead {
            throw SessionTestError.storage
        }; return records[ownerID]
    }

    func save(_ pending: PendingOnboarding) throws {
        guard records[pending.ownerID] == nil || records[pending.ownerID] == pending
        else { throw OnboardingJournalFailure.conflict }
        records[pending.ownerID] = pending
        if failSave {
            throw SessionTestError.storage
        }
    }

    func clear(_ pending: PendingOnboarding) throws {
        if failClear {
            throw SessionTestError.storage
        }
        guard records[pending.ownerID] == nil || records[pending.ownerID] == pending
        else { throw OnboardingJournalFailure.conflict }
        records[pending.ownerID] = nil
        if failAfterClear {
            throw SessionTestError.storage
        }
    }

    func saved(_ id: OnboardingID) -> PendingOnboarding? {
        records.values.first { $0.runID == id }
    }
}

actor LearningCall {
    let kind: String, token: String
    let id: OnboardingID
    let version: Int?
    let confirmation: String?
    let saved: PendingOnboarding?
    private var continuation: CheckedContinuation<OnboardingRun, Error>?
    private var response: Result<OnboardingRun, Error>?
    private(set) var completed = false
    init(
        _ kind: String,
        token: String,
        id: OnboardingID,
        version: Int?,
        confirmation: String?,
        saved: PendingOnboarding?
    ) {
        self.kind = kind; self.token = token; self.id = id; self.version = version; self
            .confirmation = confirmation; self.saved = saved
    }

    /// Deliberately noncooperative to exercise late results after local cancellation.
    func result() async throws -> OnboardingRun {
        defer { completed = true }
        if let response {
            return try response.get()
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func finish(_ result: Result<OnboardingRun, Error>) {
        guard response == nil else { return }; response = result
        continuation?.resume(with: result); continuation = nil
    }
}

actor QueuedLearningGateway: OnboardingGateway {
    private let journal: MemoryOnboardingJournal
    private var queue: [LearningCall] = []
    private(set) var observed: [LearningCall] = []
    init(_ journal: MemoryOnboardingJournal) {
        self.journal = journal
    }

    func pop() -> LearningCall? {
        queue.isEmpty ? nil : queue.removeFirst()
    }

    private func call(
        _ kind: String,
        _ token: String,
        _ id: OnboardingID,
        _ version: Int? = nil,
        _ confirmation: String? = nil
    ) async throws -> OnboardingRun {
        let call = await LearningCall(
            kind,
            token: token,
            id: id,
            version: version,
            confirmation: confirmation,
            saved: journal.saved(id)
        )
        observed.append(call); queue.append(call)
        return try await call.result()
    }

    func start(token: String, id: OnboardingID, form _: OnboardingForm,
               model _: String?) async throws -> OnboardingRun
    {
        try await call(
            "start",
            token,
            id
        )
    }

    func read(token: String, id: OnboardingID) async throws -> OnboardingRun {
        try await call("read", token, id)
    }

    func answer(token: String, id: OnboardingID, version: Int, stepID _: String,
                answer _: String) async throws -> OnboardingRun
    {
        try await call(
            "answer",
            token,
            id,
            version
        )
    }

    func revise(
        token: String,
        id: OnboardingID,
        version: Int,
        goal _: String,
        dailyMinutes _: Int,
        targetDate _: String?,
        timezone _: String
    ) async throws -> OnboardingRun {
        try await call("revise", token, id, version)
    }

    func confirm(token: String, id: OnboardingID, version: Int,
                 requestID: String) async throws -> OnboardingRun
    {
        try await call(
            "confirm",
            token,
            id,
            version,
            requestID
        )
    }

    func cancel(token: String, id: OnboardingID) async throws -> OnboardingRun {
        try await call("cancel", token, id)
    }

    func retry(token: String, id: OnboardingID, version: Int) async throws -> OnboardingRun {
        try await call(
            "retry",
            token,
            id,
            version
        )
    }

    func close() async {
        for call in observed {
            await call.finish(.failure(CancellationError()))
        }
    }
}

@MainActor
final class LearningHarness {
    let auth: FakeSessionGateway
    let session: SessionStore
    let journal = MemoryOnboardingJournal()
    let gateway: QueuedLearningGateway
    let model: OnboardingModel
    init(polls: [UInt64] = []) throws {
        auth = try FakeSessionGateway(sessionGrant())
        session = SessionStore(gateway: auth, vault: MemoryTokenVault())
        gateway = QueuedLearningGateway(journal)
        model = OnboardingModel(session: session, gateway: gateway, journal: journal, pollDelays: polls)
    }

    func login(_ id: Int64 = 1) async throws {
        try await session.logout(); try await auth.setGrant(sessionGrant(id))
        try await session.login(email: "u@example.test", password: "synthetic")
        await model.bindAccount(session.state)
    }

    func ready() async throws {
        try await awaitHistory { self.model.state.canStart }
    }

    func next() async throws -> LearningCall {
        try await nextTurn { await self.gateway.pop() }
    }

    func finish(_ call: LearningCall, _ state: String) async throws {
        try await call.finish(.success(learningRun(state, id: call.id)))
        try await awaitHistory { !self.model.state.busy }
    }

    func close() async {
        model.close(); await gateway.close()
    }
}
