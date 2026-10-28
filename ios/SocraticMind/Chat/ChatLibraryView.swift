import CoreGraphics
import MindCore
import SwiftUI

struct ChatLibraryView: View {
    @ObservedObject var model: ChatLibraryModel
    @ObservedObject var turn: ChatTurnModel
    @ObservedObject var actions: ChatActionsModel
    let suggestions: ChatSuggestionsModel
    let models: ChatModelSelectionModel
    @ObservedObject var avatars: ChatAvatarModel
    let avatarImages: AvatarImageLoader<CGImage>?
    let account: SessionState
    let logout: () -> Void
    let newConversation: () -> Void
    let selectConversation: (String) -> Void
    let closeConversation: () -> Void
    @Environment(\.scenePhase) private var scenePhase
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
            if model.state.account == HistoryAccount.from(account), let notice = model.state.titleNotice {
                Text(notice).padding(.horizontal, 20)
            }
            if model.state.account != HistoryAccount.from(account) || turn.state.account != model.state
                .account || actions.state.account != model.state.account || avatars.state.account != model.state.account
            {
                ProgressView("正在读取会话…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.state.selected != nil {
                selectedConversation
            } else {
                header(title: "会话", loading: model.state.conversations.loading, refresh: model.refreshConversations)
                Button("新建对话", action: newConversation).disabled(!turn.state.editable)
                conversations
                ChatAvatarControls(model: avatars, images: avatarImages, target: nil, enabled: turn.state.editable)
            }
            if actions.state.dialog == nil, actions.state.account == HistoryAccount.from(account),
               let notice = actions.state.notice
            {
                Text(notice).padding(12)
            }
            if model.state.account == HistoryAccount.from(account), turn.state.account == model.state.account,
               actions.state.selectionSessionID == nil,
               case let .signedIn(user, _) = account
            {
                if actions.state.dialog == nil, let selected = model.state.selected,
                   selected.target == turn.state.target, let owner = model.state.account
                {
                    ChatModelSelector(model: models, turn: turn.state, account: owner)
                    ChatSuggestionsBar(model: suggestions, account: owner, target: selected.target, style: user.aiStyle)
                }
                ChatComposerView(model: turn, style: user.aiStyle,
                                 selected: model.state.selected != nil && model.state.selected?.target == turn.state
                                     .target)
            }
        }
        .sheet(isPresented: Binding(
            get: { actions.state.dialog != nil && actions.state.account == HistoryAccount.from(account) },
            set: {
                if !$0 {
                    actions.cancelDialog()
                }
            }
        )) {
            ChatActionSheet(model: actions)
        }
        .sheet(item: Binding(
            get: { avatars.state.account == HistoryAccount.from(account) ? avatars.state.picker : nil },
            set: {
                if $0 == nil {
                    avatars.dismiss()
                }
            }
        )) { picker in
            ChatAvatarPickerSheet(model: avatars, turn: turn, picker: picker, images: avatarImages)
        }
        .confirmationDialog("放弃未发送的内容？", isPresented: $discardDraft, titleVisibility: .visible) {
            Button("放弃草稿", role: .destructive, action: closeConversation)
            Button("继续编辑", role: .cancel) {}
        } message: { Text("返回会话列表会清空当前草稿。") }
        .onAppear { model.setTitlePollingActive(scenePhase == .active); suggestions.setActive(scenePhase == .active) }
        .onChange(of: scenePhase) { _, phase in
            model.setTitlePollingActive(phase == .active); suggestions.setActive(phase == .active)
        }
        .onDisappear {
            model.setTitlePollingActive(false); suggestions.setActive(false)
            Task { await renderer.clear() }
        }
    }

    @ViewBuilder
    private var selectedConversation: some View {
        if let selected = model.state.selected {
            let backAction: (() -> Void)? = turn.state.editable ? { back() } : nil
            header(title: selected.title?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty ?? "对话",
                   loading: model.state.messages.loading, back: backAction,
                   refresh: model.refreshSelectedConversation)
            ChatAvatarControls(model: avatars, images: avatarImages, target: selected.target,
                               enabled: turn.state.editable && actions.state.dialog == nil && actions.state
                                   .selectionSessionID == nil)
            if actions.state.selectionSessionID == selected.sessionID {
                ChatSelectionControls(
                    state: actions.state,
                    enabled: turn.state.editable && !actions.state.busy,
                    model: actions
                )
            } else {
                ChatManagementMenu(
                    sessionID: selected.sessionID,
                    enabled: actions.canManage(selected.sessionID),
                    model: actions,
                    messages: !model.state.messages.items.isEmpty
                )
            }
            selectedMessages(selected)
        }
    }

    @ViewBuilder
    private func selectedMessages(_ selected: ChatConversation) -> some View {
        if selected.target != turn.state.target {
            ProgressView("正在切换会话…").frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            MessageHistoryView(
                page: model.state.messages,
                renderer: renderer,
                turn: turn.state,
                regenerationID: ChatRegeneration.from(model.state)?.answerID,
                regenerate: regenerate,
                actions: actions.state,
                toggleMessage: actions.toggleMessage,
                avatar: AvatarPresentation(
                    images: avatarImages,
                    resource: avatars.state.resource(for: selected.target),
                    fallback: .fallback(for: selected.target.mode)
                ),
                refresh: model.refreshSelectedConversation,
                more: model.loadMoreMessages
            )
            .id(selected.sessionID)
        }
    }

    private func back() {
        guard turn.state.editable else { return }
        if actions.state.selectionSessionID != nil {
            actions.dismiss()
        } else if turn.state.draft.isEmpty {
            closeConversation()
        } else {
            discardDraft = true
        }
    }

    private func regenerate() {
        guard case let .signedIn(user, _) = account else { return }
        turn.regenerate(history: model.state, style: user.aiStyle)
    }

    private var conversations: some View {
        List {
            ForEach(model.state.conversations.items, id: \.sessionID) { summary in
                VStack(alignment: .leading) {
                    Button { selectConversation(summary.sessionID) } label: {
                        HStack(spacing: 12) {
                            AvatarImageView(source: AvatarPresentation(images: avatarImages,
                                                                       resource: avatars.state.resource(
                                                                           sessionID: summary.sessionID,
                                                                           mode: ChatMode(rawValue: summary.mode) ??
                                                                               .normal
                                                                       ),
                                                                       fallback: .fallback(
                                                                           for: ChatMode(rawValue: summary
                                                                               .mode) ?? .normal
                                                                       )))
                            VStack(alignment: .leading, spacing: 6) {
                                Text(summary.title?.trimmingCharacters(in: .whitespacesAndNewlines)
                                    .nilIfEmpty ?? "未命名对话")
                                    .font(.headline).foregroundStyle(.primary).lineLimit(2)
                                Text(summary.preview.nilIfEmpty ?? "暂无文字预览").font(.subheadline)
                                    .foregroundStyle(.secondary).lineLimit(2)
                            }.padding(.vertical, 6)
                        }
                    }
                    .buttonStyle(.plain)
                    .disabled(!turn.state.editable)
                    ChatManagementMenu(
                        sessionID: summary.sessionID,
                        enabled: actions.canManage(summary.sessionID),
                        model: actions
                    )
                }
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

private extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}
