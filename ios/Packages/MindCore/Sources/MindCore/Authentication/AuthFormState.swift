import Foundation

public protocol AccountRecoveryGateway: Sendable {
    func sendCode(email: String, purpose: CodePurpose) async throws -> String
    func resetPassword(email: String, code: String, newPassword: String) async throws -> String
}

public enum AuthMode: String, CaseIterable, Sendable { case login, register, reset }
public enum AuthField: Hashable, Sendable { case username, email, password, confirmation, code }
public enum AuthOperation: Sendable { case submit, sendCode }

/// Memory only: never persist the form or put it in diagnostics / saved scene state.
public struct AuthFormState: Sendable, CustomStringConvertible {
    public var mode: AuthMode = .login
    public var username = ""
    public var email = ""
    public var password = ""
    public var confirmation = ""
    public var code = ""
    public var busy: AuthOperation?
    public var cooldownSeconds = 0
    public var error: String?
    public var notice: String?
    public var description: String {
        "AuthFormState(mode=\(mode), fields=<redacted>)"
    }
}

func normalizedFormEmail(_ value: String) -> String {
    value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
}

extension AuthFormState {
    func validation(codeOnly: Bool) -> String? {
        let address = normalizedFormEmail(email)
        if address.isEmpty {
            return "请输入邮箱"
        }
        if address.range(of: "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$", options: .regularExpression) == nil {
            return "请检查邮箱格式"
        }
        if codeOnly {
            return nil
        }
        if mode == .register, username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "请输入用户名"
        }
        if password.isEmpty {
            return "请输入密码"
        }
        if mode != .login, password != confirmation {
            return "两次输入的密码不一致"
        }
        if mode != .login, code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "请输入验证码"
        }
        return nil
    }
}

public func accountErrorMessage(_ error: Error) -> String {
    if let failure = error as? HTTPFailure {
        return failure.userMessage
    }
    if let failure = error as? SessionFailure {
        switch failure {
        case .storage: return "无法完成安全存储，请重试；如注册已完成，可改用登录。"
        case .busy: return "账号操作正在进行，请稍后再试。"
        case .notSignedIn, .superseded: return "登录状态已变化，请重新操作。"
        }
    }
    if error is URLError {
        return "暂时无法连接服务，请检查网络后重试。已提交的操作可能已完成，请勿连续重复提交。"
    }
    return "暂时无法完成操作，请稍后重试。"
}
