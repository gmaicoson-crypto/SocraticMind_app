import Foundation

/// Presentation of an authoritative outcome; never retries or changes turn ownership.
enum ChatTurnOutcome {
    static func notice(pending: PendingChatTurn, remote: RemoteChatTurn?, messages: [StoredChatMessage],
                       rejectedModel: Bool) -> String?
    {
        if rejectedModel {
            return "所选模型不可用，请刷新模型目录或重新选择后发送；输入与原回答已保留。"
        }
        guard let remote else { return "消息已更新或删除，请刷新历史查看。" }
        let regeneration = pending.regenerateMessageID != nil && remote.status != .complete
        if !regeneration, remote.ids != nil, messages.count != 2 {
            return "消息已更新或删除，请刷新历史查看。"
        }
        if remote.status == .complete {
            return nil
        }
        let stored = messages.first { $0.role == "ai" && $0.id == remote.ids?.ai }.flatMap(ChatAnswerFeedback.from)
        let feedback = ChatAnswerFeedback(usage: remote.feedback?.usage ?? stored?.usage,
                                          failure: remote.feedback?.failure ?? stored?.failure)
        let fallback: String = if remote.status == .interrupted {
            regeneration ? "重新生成已停止，原回答仍保留。" : "回复已停止；已保存的部分可在历史中查看。"
        } else {
            regeneration ? "重新生成失败，原回答仍保留。" : "本次回复失败；可查看已有内容后重新输入。"
        }
        let reason = feedback.failure.map { regeneration ? "\($0.message) 原回答仍保留。" : $0.message } ?? fallback
        if regeneration, remote.feedback != nil || stored?.usage != nil {
            return "\(reason)\n本次重生成：\(feedback.usageSummary)\n\(ChatAnswerFeedback.scopeNote)"
        }
        return reason
    }
}
