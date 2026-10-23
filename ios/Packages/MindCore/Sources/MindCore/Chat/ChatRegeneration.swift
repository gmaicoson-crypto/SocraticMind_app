import Foundation

/// Eligibility from the latest loaded question. The server arbitrates concurrent history changes.
public struct ChatRegeneration: Sendable {
    public let account: HistoryAccount
    public let target: ChatTarget
    public let answerID: Int64
    public let input: String

    private init(account: HistoryAccount, target: ChatTarget, answerID: Int64, input: String) {
        self.account = account; self.target = target; self.answerID = answerID; self.input = input
    }

    public static func from(_ history: ChatLibraryState) -> ChatRegeneration? {
        let page = history.messages
        guard let account = history.account, let target = history.selected?.target,
              page.loaded, page.loading == nil, page.failure == nil,
              let question = page.items.filter({ $0.role == "user" }).max(by: { $0.id < $1.id }),
              let answer = page.items.filter({ $0.role == "ai" }).max(by: { $0.id < $1.id }),
              answer.id > question.id,
              !question.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              question.content.unicodeScalars.count <= 5000,
              [question, answer].allSatisfy({ supports($0, target: target) })
        else { return nil }
        return ChatRegeneration(account: account, target: target, answerID: answer.id, input: question.content)
    }

    private static func supports(_ message: StoredChatMessage, target: ChatTarget) -> Bool {
        guard message.messageType == "chat", message.sessionID == target.sessionID,
              message.nodeKey == target.nodeKey, message.mode == target.mode.rawValue,
              (message.topicID ?? 0) == target.topicID, message.attachments.isEmpty
        else { return false }
        guard let metadata = message.metadata else { return true }
        if let kind = metadata["kind"], kind != .string("qa") {
            return false
        }
        if let status = metadata["status"],
           !["complete", "failed", "interrupted"].map(ChatJSONValue.string).contains(status)
        {
            return false
        }
        // Quotes / attachments require their own complete snapshot; never silently drop that context.
        return ["quote", "quote_source_id"].allSatisfy { metadata[$0] == nil || metadata[$0] == .null } &&
            (metadata["attachment_snapshot"] == nil || metadata["attachment_snapshot"] == .array([]))
    }
}
