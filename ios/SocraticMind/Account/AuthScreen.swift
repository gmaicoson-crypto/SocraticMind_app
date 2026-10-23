import MindCore
import SwiftUI

struct AuthScreen: View {
    @ObservedObject var model: AuthFormModel
    let expired: Bool
    let submit: () -> Void
    let sendCode: () -> Void
    @Environment(\.scenePhase) private var phase

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("SocraticMind").font(.largeTitle.bold()).foregroundStyle(.tint)
                Text("从一个好问题开始").font(.headline)
                HStack(spacing: 24) {
                    Button("登录") { model.switchMode(.login) }.accessibilityIdentifier("auth.mode.login")
                    Button("创建账号") { model.switchMode(.register) }.accessibilityIdentifier("auth.mode.register")
                }.disabled(model.state.busy != nil)
                Text(title).font(.title2).accessibilityAddTraits(.isHeader)
                if expired {
                    Text("登录已失效，请重新登录。").foregroundStyle(.red)
                }
                AuthFields(model: model, submit: submit).id(model.state.mode)
                if model.state.mode != .login {
                    Button(codeTitle, action: sendCode)
                        .accessibilityIdentifier("auth.sendCode")
                        .disabled(model.state.busy != nil || model.state.cooldownSeconds > 0)
                }
                if let error = model.state.error {
                    Text(error).foregroundStyle(.red).accessibilityLabel("错误：\(error)")
                }
                if let notice = model.state.notice {
                    Text(notice).foregroundStyle(.secondary)
                }
                Button(action: submit) {
                    Text(submitTitle).frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("auth.submit")
                .disabled(model.state.busy != nil)
                if model.state.mode == .login {
                    Button("忘记密码？") { model.switchMode(.reset) }
                        .accessibilityIdentifier("auth.forgot").disabled(model.state.busy != nil)
                } else if model.state.mode == .reset {
                    Button("返回登录") { model.switchMode(.login) }.disabled(model.state.busy != nil)
                }
            }
            .frame(maxWidth: 520)
            .padding(24)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .onChange(of: phase) {
            _, next in if next == .active {
                model.refreshClock()
            }
        }
        .task(id: phase == .active && model.state.cooldownSeconds > 0) {
            guard phase == .active, model.state.cooldownSeconds > 0 else { return }
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(1)) } catch { return }
                model.refreshClock()
            }
        }
    }

    private var title: String {
        switch model.state.mode {
        case .login: "欢迎回来"
        case .register: "创建你的账号"
        case .reset: "找回密码"
        }
    }

    private var submitTitle: String {
        if model.state.busy == .submit {
            return "正在处理…"
        }
        return switch model.state.mode {
        case .login: "登录"
        case .register: "注册并登录"
        case .reset: "更新密码"
        }
    }

    private var codeTitle: String {
        if model.state.busy == .sendCode {
            return "正在发送…"
        }
        if model.state.cooldownSeconds > 0 {
            return "\(model.state.cooldownSeconds) 秒后可重发"
        }
        return "发送验证码"
    }
}
