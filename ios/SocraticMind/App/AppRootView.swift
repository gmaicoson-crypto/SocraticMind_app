import MindCore
import SwiftUI

struct AppRootView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        Group {
            if let error = model.configurationError {
                SessionPanel(title: "暂时无法连接学习空间", message: error)
            } else {
                sessionContent
            }
        }
        .tint(Color(red: 0.39, green: 0.31, blue: 0.64))
        .task { model.start() }
    }

    @ViewBuilder
    private var sessionContent: some View {
        switch model.session {
        case .uninitialized, .restoring:
            SessionPanel(title: "正在恢复登录", message: "正在验证你的账号…", loading: true)
        case .clearing:
            SessionPanel(title: "正在退出", message: "正在清理本机登录信息…", loading: true)
        case let .signedIn(user, revision):
            if let history = model.history, let turn = model.turn, let actions = model.actions,
               let suggestions = model.suggestions, let avatars = model.avatars
            {
                ChatLibraryView(
                    model: history,
                    turn: turn,
                    actions: actions,
                    suggestions: suggestions,
                    avatars: avatars,
                    avatarImages: model.avatarImages,
                    account: .signedIn(user: user, revision: revision),
                    logout: model.logout,
                    newConversation: model.newConversation,
                    selectConversation: model.selectConversation,
                    closeConversation: model.closeConversation
                )
                .id(revision)
            }
        case let .unavailable(storage, retry):
            SessionPanel(title: storage ? "登录信息暂不可用" : "暂时无法验证账号",
                         message: model.error ?? (storage ? "请解锁设备后重试；也可以清理本机登录信息。" : "请检查服务和网络，恢复后重试。"),
                         action: retry ? { model.restore() } : nil, clear: model.logout)
        case .signedOut, .authenticating:
            if let form = model.form {
                AuthScreen(model: form, expired: model.session == .signedOut(expired: true),
                           submit: model.submit, sendCode: model.sendCode)
            }
        }
    }
}

private struct SessionPanel: View {
    let title: String
    let message: String
    var loading = false
    var action: (() -> Void)?
    var clear: (() -> Void)?

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                Text("SocraticMind").font(.headline).foregroundStyle(.tint)
                Text(title).font(.title2).accessibilityAddTraits(.isHeader)
                Text(message).foregroundStyle(.secondary)
                if loading {
                    ProgressView().accessibilityLabel(title)
                }
                if let action {
                    Button("重试", action: action).buttonStyle(.borderedProminent)
                }
                if let clear {
                    Button("清理本机登录并退出", action: clear).buttonStyle(.bordered)
                }
            }
            .frame(maxWidth: 520)
            .padding(24)
            .frame(maxWidth: .infinity)
        }
    }
}
