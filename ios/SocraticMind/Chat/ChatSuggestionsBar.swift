import MindCore
import SwiftUI

struct ChatSuggestionsBar: View {
    @ObservedObject var model: ChatSuggestionsModel
    let account: HistoryAccount
    let target: ChatTarget
    let style: String

    var body: some View {
        if let context = model.state.context, context.account == account, context.target == target {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(model.state.source == .ai ? "AI 建议" : "参考话题").font(.caption)
                    Button(model.state.loading ? "正在获取…" : "换一批", action: model.refresh)
                        .disabled(!model.state.enabled || model.state.loading || model.state.choice != nil)
                }
                ScrollView(.horizontal) {
                    LazyHStack(spacing: 8) {
                        ForEach(model.state.items, id: \.self) { text in
                            Button { Task { await model.choose(text, context: context, style: style) } } label: {
                                Text(text).lineLimit(2).frame(maxWidth: 260)
                            }
                            .buttonStyle(.bordered).disabled(!model.state.enabled)
                            .accessibilityLabel("发送建议：\(text)")
                        }
                    }
                }
                if let notice = model.state.notice {
                    Text(notice).font(.caption)
                }
            }
            .padding(.horizontal, 20)
            .alert("替换草稿并发送？", isPresented: Binding(
                get: { model.state.choice != nil }, set: {
                    if !$0 {
                        model.cancelChoice()
                    }
                }
            )) {
                Button("替换并发送") { model.confirmChoice(style: style) }
                Button("保留草稿", role: .cancel, action: model.cancelChoice)
            } message: { Text(model.state.choice?.text ?? "") }
        }
    }
}
