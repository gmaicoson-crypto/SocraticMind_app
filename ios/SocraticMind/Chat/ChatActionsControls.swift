import MindCore
import SwiftUI

struct ChatManagementMenu: View {
    let sessionID: String
    let enabled: Bool
    let model: ChatActionsModel
    var messages = false

    var body: some View {
        Menu("管理会话") {
            Button("重命名") { model.rename(sessionID) }
            Button("删除整个会话", role: .destructive) { model.deleteSession(sessionID) }
            if messages {
                Button("选择消息", action: model.selectMessages)
            }
        }
        .disabled(!enabled)
        .buttonStyle(.borderless)
    }
}

struct ChatSelectionControls: View {
    let state: ChatActionsState
    let enabled: Bool
    let model: ChatActionsModel

    var body: some View {
        VStack(alignment: .leading) {
            Text("已选择 \(state.selectedIDs.count) 条消息（最多 100 条）")
            HStack {
                Button("删除所选", role: .destructive, action: model.deleteSelectedMessages)
                    .disabled(!enabled || state.selectedIDs.isEmpty)
                Button("结束选择", action: model.dismiss).disabled(state.busy)
            }
        }.padding(.horizontal, 20)
    }
}

struct ChatActionSheet: View {
    @ObservedObject var model: ChatActionsModel

    private var renaming: Bool {
        if case .rename = model.state.dialog {
            return true
        }; return false
    }

    var body: some View {
        NavigationStack {
            Form {
                if let dialog = model.state.dialog {
                    switch dialog {
                    case let .rename(_, title):
                        TextField("会话标题", text: Binding(get: { title }, set: model.editTitle))
                            .disabled(model.state.busy).accessibilityIdentifier("chat_title_input")
                        Text("\(title.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.count) / 40 字")
                            .foregroundStyle(.secondary)
                    case let .deleteSession(_, title, discardsDraft):
                        Text("删除“\(title.isEmpty ? "未命名对话" : title)”及其消息？此操作无法撤销。")
                        if discardsDraft {
                            Text("当前未发送的草稿也会清空。")
                        }
                    case let .deleteMessages(_, ids):
                        Text("删除所选 \(ids.count) 条消息？此操作无法撤销。")
                    }
                }
                if let notice = model.state.notice {
                    Text(notice).foregroundStyle(.red)
                }
                if model.state.busy {
                    ProgressView("正在处理…")
                }
            }
            .navigationTitle(renaming ? "重命名会话" : "确认删除")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消", action: model.cancelDialog).disabled(model.state.busy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(renaming ? "保存" : "删除", role: renaming ? nil : .destructive, action: model.confirm)
                        .disabled(!model.state.canConfirm).accessibilityIdentifier("chat_action_confirm")
                }
            }
        }
        .interactiveDismissDisabled(model.state.busy)
        .presentationDetents([.medium, .large])
    }
}
