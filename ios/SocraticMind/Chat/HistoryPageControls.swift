import MindCore
import SwiftUI

struct HistoryPageControls<Item: Sendable>: View {
    let page: HistoryPageState<Item>
    let emptyText: String
    let moreText: String
    let refresh: () -> Void
    let more: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let loading = page.loading {
                ProgressView(loading == .more ? "正在读取更多…" : "正在刷新…")
            } else if let failure = page.failure {
                Text(failure.message).foregroundStyle(.red)
                Button("重试", action: failure.operation == .more ? more : refresh)
            } else if page.loaded, page.items.isEmpty {
                Text(emptyText).foregroundStyle(.secondary)
            } else if page.nextCursor != nil {
                Button(moreText, action: more)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 8)
    }
}
