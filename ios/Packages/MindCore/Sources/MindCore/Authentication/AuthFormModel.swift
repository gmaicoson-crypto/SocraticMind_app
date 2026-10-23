import Combine
import Foundation

/// Main-actor form state; SessionStore remains the sole credential and account owner.
@MainActor
public final class AuthFormModel: ObservableObject {
    @Published public private(set) var state = AuthFormState()
    private let session: SessionStore
    private let recovery: any AccountRecoveryGateway
    private let now: () -> TimeInterval
    private var generation: UInt64 = 0
    private var deadlines: [String: TimeInterval] = [:]

    public init(session: SessionStore, recovery: any AccountRecoveryGateway,
                now: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime })
    {
        self.session = session
        self.recovery = recovery
        self.now = now
    }

    public func edit(_ field: AuthField, value: String) {
        guard state.busy == nil else { return }
        var updated = state
        switch field {
        case .username: updated.username = value
        case .email: updated.email = value; updated.code = ""
        case .password: updated.password = value
        case .confirmation: updated.confirmation = value
        case .code: updated.code = value
        }
        updated.error = nil
        updated.notice = nil
        updated.cooldownSeconds = remaining(updated.email)
        state = updated
    }

    public func switchMode(_ mode: AuthMode) {
        guard state.busy == nil, state.mode != mode else { return }
        generation += 1
        state.mode = mode
        state.password = ""
        state.confirmation = ""
        state.code = ""
        state.error = nil
        state.notice = nil
        refreshClock()
    }

    public func refreshClock() {
        let seconds = remaining(state.email)
        if seconds != state.cooldownSeconds {
            state.cooldownSeconds = seconds
        }
    }

    public func reset() {
        generation += 1
        deadlines.removeAll()
        state = AuthFormState()
    }

    public func submit() async {
        guard let (ticket, input) = await begin(.submit) else { return }
        do {
            var notice: String?
            switch input.mode {
            case .login: try await session.login(email: input.email, password: input.password)
            case .register:
                try await session.register(username: input.username, email: input.email,
                                           password: input.password, code: input.code)
            case .reset:
                _ = try await recovery.resetPassword(email: input.email, code: input.code, newPassword: input.password)
                notice = "密码已更新，请使用新密码登录。"
            }
            try Task.checkCancellation()
            finish(ticket) {
                $0.mode = .login; $0.password = ""; $0.confirmation = ""; $0.code = ""; $0.notice = notice
            }
        } catch { failed(ticket, error) }
    }

    public func sendCode() async {
        guard let (ticket, input) = await begin(.sendCode) else { return }
        do {
            let message = try await recovery.sendCode(email: input.email,
                                                      purpose: input.mode == .register ? .register : .reset)
            try Task.checkCancellation()
            finish(ticket) { $0.notice = message }
        } catch { failed(ticket, error) }
    }

    private func begin(_ operation: AuthOperation) async -> (UInt64, AuthFormState)? {
        guard state.busy == nil else { return nil }
        // Reserve before awaiting the account actor so two taps cannot both pass the guard.
        let input = state
        if operation == .sendCode, input.mode == .login {
            return nil
        }
        if let error = input.validation(codeOnly: operation == .sendCode) {
            state.error = error; state.notice = nil; return nil
        }
        if operation == .sendCode, remaining(input.email) > 0 {
            refreshClock(); return nil
        }
        generation += 1
        let ticket = generation
        state.busy = operation
        state.error = nil
        state.notice = nil
        let current = await session.state
        guard ticket == generation else { return nil }
        guard case .signedOut = current, !Task.isCancelled else {
            state.busy = nil; return nil
        }
        if operation == .sendCode {
            let time = now()
            deadlines = deadlines.filter { $0.value > time }
            // The server shares a 60-second email limit across register and reset.
            deadlines[normalizedFormEmail(input.email)] = time + 60
            refreshClock()
        }
        return (ticket, input)
    }

    private func remaining(_ email: String) -> Int {
        guard let deadline = deadlines[normalizedFormEmail(email)] else { return 0 }
        return Int(ceil(max(0, deadline - now())))
    }

    private func finish(_ ticket: UInt64, update: (inout AuthFormState) -> Void) {
        guard ticket == generation else { return }
        update(&state)
        state.busy = nil
        refreshClock()
    }

    private func failed(_ ticket: UInt64, _ error: Error) {
        finish(ticket) {
            $0.error = error is CancellationError ? nil : accountErrorMessage(error)
            $0.notice = nil
        }
    }
}
