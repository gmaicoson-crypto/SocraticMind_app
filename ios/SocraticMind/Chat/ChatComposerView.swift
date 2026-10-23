import MindCore
import SwiftUI

struct ChatComposerView: View {
    @ObservedObject var model: ChatTurnModel
    let style: String
    let selected: Bool

    private var status: String? {
        if let notice = model.state.notice {
            return notice
        }
        return switch model.state.phase {
        case .restoring: "正在核对上次请求…"
        case .preparing: "正在准备发送…"
        case .sending: "正在回复，显示内容尚未确认。"
        default: nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let status {
                Text(status).font(.caption).accessibilityIdentifier("chat_status")
            }
            if selected {
                TextField("输入消息", text: Binding(get: { model.state.draft }, set: model.edit), axis: .vertical)
                    .lineLimit(1 ... 5).textFieldStyle(.roundedBorder)
                    .disabled(!model.state.editable).accessibilityIdentifier("chat_input")
                Text("\(model.state.characterCount) / 5000").font(.caption)
                    .foregroundStyle(model.state.characterCount > 5000 ? Color.red : Color.secondary)
            }
            HStack {
                if model.state.canVerify {
                    Button("核对状态", action: model.verify).accessibilityIdentifier("chat_verify")
                }
                if model.state.canStop {
                    Button("停止回复", action: model.stop).accessibilityIdentifier("chat_stop")
                }
                Spacer()
                if selected {
                    Button("发送") { model.send(style: style) }.buttonStyle(.borderedProminent)
                        .disabled(!model.state.canSend).accessibilityIdentifier("chat_send")
                }
            }
        }
        .padding(.horizontal, 20).padding(.vertical, 8)
    }
}
