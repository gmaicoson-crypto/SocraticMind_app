import MindCore
import SwiftUI

struct ChatLibraryView: View {
    @ObservedObject var model: ChatLibraryModel
    let account: SessionState
    let logout: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            if case let .signedIn(user, _) = account {
                VStack(alignment: .leading, spacing: 8) {
                    Text("你好，\(user.username)").font(.headline)
                    Button("清理本机登录并退出", action: logout)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20).padding(.vertical, 8)
            }
            Divider()
            if model.state.account != HistoryAccount.from(account) {
                ProgressView("正在读取会话…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let selected = model.state.selected {
                header(title: selected.title?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty ?? "对话",
                       loading: model.state.messages.loading, back: model.closeConversation,
                       refresh: model.refreshMessages)
                MessageHistoryView(
                    page: model.state.messages,
                    refresh: model.refreshMessages,
                    more: model.loadMoreMessages
                )
                .id(selected.sessionID)
            } else {
                header(title: "会话", loading: model.state.conversations.loading, refresh: model.refreshConversations)
                conversations
            }
        }
    }

    private var conversations: some View {
        List {
            ForEach(model.state.conversations.items, id: \.sessionID) { summary in
                Button { model.selectConversation(summary.sessionID) } label: {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(summary.title?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty ?? "未命名对话")
                            .font(.headline).foregroundStyle(.primary).lineLimit(2)
                        Text(summary.preview.nilIfEmpty ?? "暂无文字预览").font(.subheadline)
                            .foregroundStyle(.secondary).lineLimit(2)
                    }.padding(.vertical, 6)
                }
                .buttonStyle(.plain)
            }
            HistoryPageControls(page: model.state.conversations, emptyText: "暂无历史会话", moreText: "加载更多会话",
                                refresh: model.refreshConversations, more: model.loadMoreConversations)
        }
        .listStyle(.plain)
    }

    private func header(title: String, loading: HistoryLoad?, back: (() -> Void)? = nil,
                        refresh: @escaping () -> Void) -> some View
    {
        HStack(spacing: 12) {
            if let back {
                Button("返回", action: back)
            }
            Text(title).font(.title2).lineLimit(2).accessibilityAddTraits(.isHeader)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button("刷新", action: refresh).disabled(loading == .refresh)
        }
        .padding(.horizontal, 20).padding(.vertical, 12)
    }
}

private struct MessageHistoryView: View {
    let page: HistoryPageState<StoredChatMessage>
    let refresh: () -> Void
    let more: () -> Void

    var body: some View {
        ScrollViewReader { scroll in
            List {
                HistoryPageControls(page: page, emptyText: "暂无可读取的消息", moreText: "加载更早消息",
                                    refresh: refresh, more: more)
                ForEach(page.items.reversed(), id: \.id) { message in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(message.role == "user" ? "你" : "SocraticMind").font(.caption).foregroundStyle(.tint)
                        Text(verbatim: message.content).textSelection(.enabled)
                        if !message.attachments.isEmpty {
                            Text("包含 \(message.attachments.count) 个附件").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 8)
                    .listRowSeparator(.hidden)
                }
            }
            .listStyle(.plain)
            .onChange(of: page.loaded) { _, loaded in
                if loaded, let latest = page.items.first?.id {
                    scroll.scrollTo(latest, anchor: .bottom)
                }
            }
        }
    }
}

private extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}
