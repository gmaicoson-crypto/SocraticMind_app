import Foundation
@testable import MindCore
import Testing

@MainActor
struct AuthFormModelTests {
    @Test
    func sharedValidationNeverStartsAuthentication() async throws {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/fixtures/auth-form.json"))
        let fixture = try JSONDecoder().decode(ValidationFixture.self, from: data)
        for item in fixture.cases {
            let setup = try await setup()
            try setup.form.switchMode(#require(AuthMode(rawValue: item.mode)))
            for (field, value) in item.fields {
                try setup.form.edit(#require(fields[field]), value: value)
            }
            await setup.form.submit()
            #expect(setup.form.state.error == item.error)
            #expect(await setup.session.state == .signedOut(expired: false))
            #expect(setup.vault.snapshot() == nil)
        }
    }

    @Test
    func loginAndRegistrationUseSessionOwnerAndEraseSecrets() async throws {
        for mode in [AuthMode.login, .register] {
            let setup = try await setup()
            fill(setup.form, mode)
            await setup.form.submit()
            guard case .signedIn = await setup.session.state else { Issue.record("Expected account"); return }
            #expect(setup.vault.snapshot() == "synthetic-token-1")
            #expect(setup.form.state.password.isEmpty)
            #expect(setup.form.state.code.isEmpty)
            #expect(!String(describing: setup.form.state).contains("Test1234"))
        }
    }

    @Test
    func resetReturnsToLoginWithoutCreatingSession() async throws {
        let setup = try await setup()
        fill(setup.form, .reset)
        await setup.form.sendCode()
        #expect(await setup.recovery.purposes == [.reset])
        await setup.form.submit()
        #expect(await setup.recovery.resets == 1)
        #expect(setup.form.state.mode == .login)
        #expect(setup.form.state.notice == "密码已更新，请使用新密码登录。")
        #expect(setup.form.state.password.isEmpty)
        #expect(await setup.session.state == .signedOut(expired: false))
    }

    @Test
    func cooldownSharesNormalizedEmailAcrossModesAndSurvivesNetworkFailure() async throws {
        var now: TimeInterval = -61
        let setup = try await setup { now }
        fill(setup.form, .register)
        await setup.recovery.setSend { throw URLError(.notConnectedToInternet) }
        await setup.form.sendCode()
        #expect(setup.form.state.cooldownSeconds == 60)
        setup.form.switchMode(.reset)
        setup.form.edit(.email, value: " LEARNER@EXAMPLE.TEST ")
        await setup.form.sendCode()
        #expect(await setup.recovery.purposes.count == 1)
        now += 59.001
        setup.form.refreshClock()
        #expect(setup.form.state.cooldownSeconds == 1)
        now = -1
        await setup.recovery.setSend { "验证码已发送" }
        await setup.form.sendCode()
        #expect(await setup.recovery.purposes == [.register, .reset])
    }

    @Test
    func duplicateSubmissionAndEditsAreBlockedWhileRequestRuns() async throws {
        let setup = try await setup()
        fill(setup.form, .reset)
        let gate = CompletionGate<String>()
        await setup.recovery.setReset { try await gate.wait() }
        let task = Task { await setup.form.submit() }
        try await waitForGate(gate)
        await setup.form.submit()
        await setup.form.sendCode()
        setup.form.switchMode(.register)
        setup.form.edit(.email, value: "another@example.test")
        #expect(await setup.recovery.resets == 1)
        #expect(setup.form.state.email == "learner@example.test")
        #expect(setup.form.state.mode == .reset)
        #expect(await setup.recovery.purposes.isEmpty)
        await gate.finish(.success("ok"))
        await task.value
    }

    @Test
    func clearingFormDiscardsLateRecoveryResponse() async throws {
        let setup = try await setup()
        fill(setup.form, .register)
        let gate = CompletionGate<String>()
        await setup.recovery.setSend { try await gate.wait() }
        let task = Task { await setup.form.sendCode() }
        try await waitForGate(gate)
        setup.form.reset()
        await gate.finish(.success("old message"))
        await task.value
        #expect(setup.form.state.mode == .login)
        #expect(setup.form.state.email.isEmpty)
        #expect(setup.form.state.notice == nil)
        #expect(setup.form.state.busy == nil)
    }

    @Test
    func cancellationReleasesBusyStateAndBackendErrorRemainsVisible() async throws {
        let setup = try await setup()
        fill(setup.form, .reset)
        let gate = CompletionGate<String>()
        await setup.recovery.setReset { try await gate.wait() }
        let task = Task { await setup.form.submit() }
        try await waitForGate(gate)
        task.cancel()
        await task.value
        #expect(setup.form.state.busy == nil)
        #expect(setup.form.state.error == nil)
        await setup.recovery
            .setReset { throw HTTPFailure(status: 400, code: nil, userMessage: "验证码已过期", retryable: nil) }
        await setup.form.submit()
        #expect(setup.form.state.error == "验证码已过期")
        #expect(setup.form.state.mode == .reset)
    }

    private func setup(now: @escaping () -> TimeInterval = { 1 }) async throws -> Setup {
        let vault = MemoryTokenVault()
        let session = try SessionStore(gateway: FakeSessionGateway(sessionGrant()), vault: vault)
        try await session.restore()
        let recovery = FormRecovery()
        return Setup(session: session, vault: vault, recovery: recovery,
                     form: AuthFormModel(session: session, recovery: recovery, now: now))
    }

    private func fill(_ form: AuthFormModel, _ mode: AuthMode) {
        form.switchMode(mode)
        for (field, value) in [(AuthField.username, "学员"), (.email, "learner@example.test"), (.password, "Test1234"),
                               (.confirmation, "Test1234"), (.code, "123456")]
        {
            form.edit(field, value: value)
        }
    }

    private let fields: [String: AuthField] = ["username": .username, "email": .email, "password": .password,
                                               "confirmation": .confirmation, "code": .code]
    private struct ValidationFixture: Decodable {
        let cases: [Case]
        struct Case: Decodable { let mode: String; let fields: [String: String]; let error: String }
    }

    private struct Setup {
        let session: SessionStore
        let vault: MemoryTokenVault
        let recovery: FormRecovery
        let form: AuthFormModel
    }
}

private actor FormRecovery: AccountRecoveryGateway {
    private(set) var purposes: [CodePurpose] = []
    private(set) var resets = 0
    private var sendAction: @Sendable () async throws -> String = { "验证码已发送" }
    private var resetAction: @Sendable () async throws -> String = { "ok" }
    func setSend(_ action: @escaping @Sendable () async throws -> String) {
        sendAction = action
    }

    func setReset(_ action: @escaping @Sendable () async throws -> String) {
        resetAction = action
    }

    func sendCode(email _: String, purpose: CodePurpose) async throws -> String {
        purposes.append(purpose); return try await sendAction()
    }

    func resetPassword(email _: String, code _: String, newPassword _: String) async throws -> String {
        resets += 1; return try await resetAction()
    }
}
