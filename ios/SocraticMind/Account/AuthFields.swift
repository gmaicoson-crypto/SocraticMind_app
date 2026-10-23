import MindCore
import SwiftUI
import UIKit

struct AuthFields: View {
    @ObservedObject var model: AuthFormModel
    let submit: () -> Void
    @State private var focus = AuthInputFocus()
    @State private var revealPassword = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if model.state.mode == .register {
                entry("用户名", .username, hint: "2—20 个字符")
            }
            entry("邮箱", .email, keyboard: .emailAddress)
            entry(model.state.mode == .reset ? "新密码" : "密码", .password,
                  hint: model.state.mode == .login ? nil : "至少 8 位，同时包含字母和数字")
            if model.state.mode != .login {
                entry("确认密码", .confirmation)
                entry("邮箱验证码", .code, keyboard: .numberPad)
            }
            Toggle("显示密码", isOn: $revealPassword).font(.subheadline)
        }
        .disabled(model.state.busy != nil)
    }

    private func entry(_ title: String, _ field: AuthField, keyboard: UIKeyboardType = .default,
                       hint: String? = nil) -> some View
    {
        let secret = field == .password || field == .confirmation
        return VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.subheadline.weight(.medium))
            AuthTextInput(text: binding(field), title: title, identifier: "auth.\(field)",
                          secure: secret && !revealPassword, contentType: contentType(field),
                          keyboard: keyboard, focus: focus, last: isLast(field), onSubmit: { advance(field) })
            if let hint {
                Text(hint).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func binding(_ field: AuthField) -> Binding<String> {
        Binding(get: {
            switch field {
            case .username: model.state.username
            case .email: model.state.email
            case .password: model.state.password
            case .confirmation: model.state.confirmation
            case .code: model.state.code
            }
        }, set: { model.edit(field, value: $0) })
    }

    private func contentType(_ field: AuthField) -> UITextContentType {
        switch field {
        case .email: .username
        case .username: .nickname
        case .password: model.state.mode == .login ? .password : .newPassword
        case .confirmation: .newPassword
        case .code: .oneTimeCode
        }
    }

    private func isLast(_ field: AuthField) -> Bool {
        field == .code || (field == .password && model.state.mode == .login)
    }

    private func advance(_ field: AuthField) {
        if isLast(field) {
            focus.move(to: nil); submit()
        } else {
            focus.move(to: next(field).map { "auth.\($0)" })
        }
    }

    private func next(_ field: AuthField) -> AuthField? {
        switch field {
        case .username: .email
        case .email: .password
        case .password: .confirmation
        case .confirmation: .code
        case .code: nil
        }
    }
}
