import Foundation
@testable import MindCore
import Testing

private func onboardingFixture(_ name: String) throws -> LearningRow {
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0 ..< 6 {
        root.deleteLastPathComponent()
    }
    let data = try Data(contentsOf: root.appendingPathComponent("contracts/fixtures/" + name))
    return try LearningRow(JSONSerialization.jsonObject(with: data))
}

private func decodeRun(_ raw: Any?, id: OnboardingID? = nil) throws -> OnboardingRun {
    let row = try LearningRow(raw)
    let expected = try id ?? OnboardingID(row.text("run_id", 36))
    return try OnboardingRun.decode(JSONSerialization.data(withJSONObject: row.values), expected: expected)
}

struct OnboardingAPIContractTests {
    @Test
    func providerStatesProjectDiagnosisPreviewAndTerminalResults() throws {
        let data = try onboardingFixture("onboarding-runs.json")
        let responses = try LearningRow(data.optional("responses"))
        for value in responses.values.values {
            let row = try LearningRow(value), run = try decodeRun(value)
            #expect(try run.status.rawValue == (row.text("status", 40)))
            #expect(try run.version == Int(row.number("version")))
            #expect(try run.processing == (row.flag("processing")))
        }
        let preview = try #require(decodeRun(responses.optional("preview")).preview)
        #expect(preview.nodes.count == 6)
        #expect(preview.totalMinutes == 120)
        #expect(preview.timezone == "Asia/Shanghai")
        #expect(preview.diagnostic?.score == 65)
        #expect(try decodeRun(responses.optional("edited")).input?.dailyMinutes == 20)
        #expect(try decodeRun(responses.optional("completed")).result?.topicID == 1)
    }

    @Test
    func invalidIdentityVersionsDatesReferencesAndCollectionsFailClosed() throws {
        let wire = try onboardingFixture("onboarding-wire.json")
        let data = try onboardingFixture("onboarding-runs.json")
        let request = try LearningRow(data.optional("request")), id = try OnboardingID(request.text("run_id", 36))
        for item in try wire.list("invalid", 100) {
            let row = try LearningRow(item), bytes = try Data(row.text("wire", 1_048_576).utf8)
            #expect(throws: OnboardingFailure.invalidResponse) { try OnboardingRun.decode(bytes, expected: id) }
        }
    }

    @Test
    func unknownFieldsAndLegacyTerminalPayloadsPreserveSafeRecovery() throws {
        for item in try onboardingFixture("onboarding-wire.json").list("valid", 20) {
            let row = try LearningRow(item), run = try decodeRun(row.optional("response"))
            switch try row.text("id", 80) {
            case "unicode-identities":
                let preview = try #require(run.preview)
                #expect(Set(preview.nodes.map(\.identity)).count == 6)
            case "unknown-error": #expect(run.error?.code == nil); #expect(run.error?.retryable == true)
            case "legacy-cancelled": #expect(run.input == nil); #expect(run.preview == nil); #expect(run
                    .status == .cancelled)
            default: Issue.record("Unknown fixture variant")
            }
        }
    }

    @Test
    func formUsesScalarsRealCalendarDatesAndCanonicalPathIDs() throws {
        func form(topic: String = "线性代数", date: String? = nil) throws -> OnboardingForm {
            try OnboardingForm(topic: topic, goal: "学习", domain: "数学", outcome: .concept,
                               familiarity: .beginner, timezone: "Asia/Shanghai", targetDate: date)
        }
        #expect(try form(topic: String(repeating: "🙂", count: 200)).topic.unicodeScalars.count == 200)
        #expect(throws: OnboardingFailure.invalidInput) { try form(topic: String(repeating: "🙂", count: 201)) }
        for date in ["2000-02-29", "2026-12-31", "0001-01-01"] {
            _ = try form(date: date)
        }
        for date in ["1900-02-29", "2026-02-30", "2026-1-01", "0000-01-01"] {
            #expect(throws: OnboardingFailure.invalidInput) { try form(date: date) }
        }
        let id = OnboardingID.create()
        for value in ["", "../runs", "31E38ECF-638C-4B16-89DA-3EE35D576137", id.value + "\n"] {
            #expect(throws: OnboardingFailure.invalidInput) { try OnboardingID(value) }
        }
        #expect(id.value.utf8.count == 36)
    }

    @Test
    func allMutationsCarryExactFieldsVersionsAndExplicitDateClearing() async throws {
        let data = try onboardingFixture("onboarding-runs.json")
        let request = try LearningRow(data.optional("request")), id = try OnboardingID(request.text("run_id", 36))
        let form = try request.form()
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = OnboardingAPI(transport: transport)
        #expect(try await api.start(token: "onboarding-start", id: id, form: form).status == .diagnosing)
        #expect(try await api.start(token: "onboarding-model", id: id, form: form, model: "用户配置-é")
            .status == .diagnosing)
        #expect(try await api.read(token: "onboarding-read", id: id).processing)
        let responses = try LearningRow(data.optional("responses")),
            step = try decodeRun(responses.optional("diagnosing"))
        let prompt = try #require(step.step)
        let preview = try await api.answer(
            token: "onboarding-answer",
            id: id,
            version: step.version,
            stepID: prompt.id,
            answer: " 先表示向量 "
        )
        #expect(preview.status == .preview)
        let edited = try await api.revise(token: "onboarding-revise", id: id, version: preview.version,
                                          goal: form.goal, dailyMinutes: 20, targetDate: nil, timezone: form.timezone)
        #expect(edited.preview?.dailyMinutes == 20)
        #expect(edited.input?.targetDate == nil)
        let completed = try await api.confirm(
            token: "onboarding-confirm",
            id: id,
            version: edited.version,
            requestID: "fixture-confirm"
        )
        #expect(completed.status == .completed && !completed.processing)
        #expect(try await api.cancel(token: "onboarding-cancel", id: id).status == .cancelled)
        #expect(try await api.retry(token: "onboarding-retry", id: id, version: 2).status == .diagnosing)
    }

    @Test
    func httpErrorsRemainDistinctAndConfirmationNeverAutomaticallyRetries() async throws {
        let data = try onboardingFixture("onboarding-runs.json"), request = try LearningRow(data.optional("request"))
        let id = try OnboardingID(request.text("run_id", 36))
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = OnboardingAPI(transport: transport)
        for (name, status) in [("unauthorized", 401), ("missing", 404), ("conflict", 409), ("unavailable", 503)] {
            do { _ = try await api.read(token: "onboarding-" + name, id: id); Issue.record("Expected failure") }
            catch let error as HTTPFailure { #expect(error.status == status) }
        }
        let responses = try LearningRow(data.optional("responses")),
            edited = try decodeRun(responses.optional("edited"))
        do {
            _ = try await api.confirm(
                token: "onboarding-confirm-conflict",
                id: id,
                version: edited.version,
                requestID: "fixture-confirm"
            )
            Issue.record("Expected conflict")
        } catch let error as HTTPFailure { #expect(error.code == "AGENT_STATE_CONFLICT") }
        let stats = try await transport.request(
            method: "GET",
            path: "stats",
            query: ["id": "onboarding-confirm-conflict"]
        )
        #expect(try LearningRow(JSONSerialization.jsonObject(with: stats)).number("count") == 1)
    }

    @Test
    func rawMalformedNumbersRemainInvalidThroughRealTransport() async throws {
        let data = try onboardingFixture("onboarding-runs.json"), request = try LearningRow(data.optional("request"))
        let id = try OnboardingID(request.text("run_id", 36))
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = OnboardingAPI(transport: transport)
        for item in try onboardingFixture("onboarding-wire.json").list("invalid", 100) {
            let name = try LearningRow(item).text("id", 80)
            await #expect(throws: OnboardingFailure.invalidResponse) { try await api.read(
                token: "onboarding-" + name,
                id: id
            ) }
        }
    }
}
