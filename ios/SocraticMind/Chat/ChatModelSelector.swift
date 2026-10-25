import Foundation
import MindCore
import SwiftUI

struct ChatModelSelector: View {
    @ObservedObject var model: ChatModelSelectionModel
    let turn: ChatTurnState
    let account: HistoryAccount
    @State private var expanded = false

    private var enabled: Bool {
        model.state.account == account && turn.account == account && turn.editable && turn.receipt == nil
    }

    var body: some View {
        if model.state.account == account, turn.account == account {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Button("模型：\(model.state.label)") { expanded = true }
                        .lineLimit(1).disabled(!enabled).accessibilityIdentifier("model-selector")
                    Spacer()
                    Button(model.state.loading ? "刷新中…" : "刷新模型", action: model.refresh)
                        .disabled(model.state.loading).accessibilityIdentifier("model-refresh")
                }
                if !model.state.available {
                    Text("所选模型已不在目录中，请重新选择后发送。").foregroundStyle(.red)
                }
                if let notice = model.state.notice {
                    Text(notice).font(.footnote)
                }
            }
            .padding(.horizontal, 12)
            .sheet(isPresented: $expanded) { choices }
            .onChange(of: enabled) {
                _, value in if !value {
                    expanded = false
                }
            }
        }
    }

    private var choices: some View {
        NavigationStack {
            List {
                Section {
                    Text("提问、相关对话和附件会经后端发送给所选模型。目录只表示已配置，不代表调用可用或免费。")
                        .font(.footnote)
                    choice("服务端默认", detail: "使用后端配置的默认模型", id: nil)
                }
                section(.environment, title: "系统模型")
                section(.custom, title: "我的模型")
                if model.state.catalog?.models.isEmpty == true {
                    Text("暂无可选模型。可稍后刷新，或尝试服务端默认。")
                }
                if model.state.loading {
                    ProgressView("正在读取模型目录…")
                }
            }
            .navigationTitle("选择模型")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("关闭") { expanded = false } } }
        }
    }

    @ViewBuilder
    private func section(_ source: ChatModelSource, title: String) -> some View {
        let options = model.state.catalog?.models.filter { $0.source == source } ?? []
        if !options.isEmpty {
            Section(title) {
                ForEach(options, id: \.identity) { option in
                    choice(option.name, detail: option.model, id: option.id)
                }
            }
        }
    }

    private func choice(_ title: String, detail: String, id: String?) -> some View {
        let selected = model.state.selectedID.map { Data($0.utf8) } == id.map { Data($0.utf8) }
        return Button {
            expanded = false
            Task { await model.select(id, account: account) }
        } label: {
            HStack {
                VStack(alignment: .leading) {
                    Text(title)
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if selected {
                    Image(systemName: "checkmark").accessibilityLabel("已选中")
                }
            }
        }
        .disabled(!enabled)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}
