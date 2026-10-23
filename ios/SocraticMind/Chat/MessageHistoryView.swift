import MindCore
import SwiftUI

struct MessageHistoryView: View {
    let page: HistoryPageState<StoredChatMessage>
    let renderer: MarkdownRenderer
    let turn: ChatTurnState
    let regenerationID: Int64?
    let regenerate: () -> Void
    let actions: ChatActionsState
    let toggleMessage: (Int64) -> Void
    let refresh: () -> Void
    let more: () -> Void

    var body: some View {
        ScrollViewReader { scroll in
            List {
                HistoryPageControls(page: page, emptyText: "暂无可读取的消息", moreText: "加载更早消息",
                                    refresh: refresh, more: more)
                ForEach(page.items.reversed().filter(turn.showsInHistory), id: \.id) { message in
                    if actions.selectionSessionID == message.sessionID {
                        Button { toggleMessage(message.id) } label: {
                            Label(
                                "选择这条消息",
                                systemImage: actions.selectedIDs.contains(message.id) ? "checkmark.circle.fill" : "circle"
                            )
                        }
                        .disabled(!turn.editable || actions.busy)
                        .buttonStyle(.borderless)
                        .accessibilityValue(actions.selectedIDs.contains(message.id) ? "已选择" : "未选择")
                        .accessibilityIdentifier("chat_select_\(message.id)")
                    }
                    MessageContentView(message: message, renderer: renderer).listRowSeparator(.hidden)
                    if message.id == regenerationID, actions.selectionSessionID == nil {
                        Button("重新生成回答", action: regenerate).disabled(!turn.canRegenerate)
                            .buttonStyle(.borderless)
                            .accessibilityIdentifier("chat_regenerate")
                    }
                }
                if turn.pending != nil {
                    if turn.pending?.regenerateMessageID != nil {
                        Text("正在重新生成，完成前保留原回答。")
                    } else if !turn.submitted.isEmpty {
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
