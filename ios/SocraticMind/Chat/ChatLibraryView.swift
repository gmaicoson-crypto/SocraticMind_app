import MindCore
import SwiftUI

struct ChatLibraryView: View {
    @ObservedObject var model: ChatLibraryModel
    @ObservedObject var turn: ChatTurnModel
    let account: SessionState
    let logout: () -> Void
    let newConversation: () -> Void
    let selectConversation: (String) -> Void
    let closeConversation: () -> Void
    @State private var renderer = MarkdownRenderer()
    @State private var discardDraft = false

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
            if model.state.account != HistoryAccount.from(account) || turn.state.account != model.state.account {
                ProgressView("正在读取会话…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let selected = model.state.selected {
                header(title: selected.title?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty ?? "对话",
                       loading: model.state.messages.loading, back: turn.state.editable ? back : nil,
                       refresh: model.refreshMessages)
                if selected.target != turn.state.target {
                    ProgressView("正在切换会话…").frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    MessageHistoryView(
                        page: model.state.messages,
                        renderer: renderer,
                        turn: turn.state,
                        refresh: model.refreshMessages,
                        more: model.loadMoreMessages
                    )
                    .id(selected.sessionID)
                }
            } else {
                header(title: "会话", loading: model.state.conversations.loading, refresh: model.refreshConversations)
                Button("新建对话", action: newConversation).disabled(!turn.state.editable)
                conversations
            }
            if model.state.account == HistoryAccount.from(account), turn.state.account == model.state.account,
               case let .signedIn(user, _) = account
            {
                ChatComposerView(model: turn, style: user.aiStyle,
                                 selected: model.state.selected != nil && model.state.selected?.target == turn.state
                                     .target)
            }
        }
        .confirmationDialog("放弃未发送的内容？", isPresented: $discardDraft, titleVisibility: .visible) {
            Button("放弃草稿", role: .destructive, action: closeConversation)
            Button("继续编辑", role: .cancel) {}
        } message: { Text("返回会话列表会清空当前草稿。") }
        .onDisappear { Task { await renderer.clear() } }
    }

    private func back() {
        guard turn.state.editable else { return }
        if turn.state.draft.isEmpty {
            closeConversation()
        } else {
            discardDraft = true
        }
    }

    private var conversations: some View {
        List {
            ForEach(model.state.conversations.items, id: \.sessionID) { summary in
                Button { selectConversation(summary.sessionID) } label: {
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
    let renderer: MarkdownRenderer
    let turn: ChatTurnState
    let refresh: () -> Void
    let more: () -> Void

    var body: some View {
        ScrollViewReader { scroll in
            List {
                HistoryPageControls(page: page, emptyText: "暂无可读取的消息", moreText: "加载更早消息",
                                    refresh: refresh, more: more)
                ForEach(page.items.reversed().filter {
                    turn.pending == nil || ($0.id != turn.ids?.user && $0.id != turn.ids?.ai)
                }, id: \.id) { message in
                    MessageContentView(message: message, renderer: renderer).listRowSeparator(.hidden)
                }
                if turn.pending != nil {
                    if !turn.submitted.isEmpty {
                        MessageContentView(role: "user", content: turn.submitted, renderer: renderer)
                    }
                    MessageContentView(role: "ai", content: turn.partial, renderer: renderer, provisional: true)
                        .id("pending-turn")
                }
            }
            .listStyle(.plain)
            .onChange(of: turn.pending?.requestID, initial: true) { _, pending in
                if pending != nil {
                    scroll.scrollTo("pending-turn", anchor: .bottom)
                }
            }
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
