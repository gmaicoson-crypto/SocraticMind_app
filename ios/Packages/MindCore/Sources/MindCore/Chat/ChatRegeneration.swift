import Foundation

/// Eligibility preserves the original context; source availability is still checked by the server.
public struct ChatRegeneration: Sendable {
    public let account: HistoryAccount
    public let target: ChatTarget
    public let answerID: Int64
    public let input: String
    public let context: ChatRequestContext

    private init(account: HistoryAccount, target: ChatTarget, answerID: Int64, input: String,
                 context: ChatRequestContext)
    {
        self.account = account; self.target = target; self.answerID = answerID; self.input = input; self
            .context = context
    }

    public static func from(_ history: ChatLibraryState) -> ChatRegeneration? {
        let page = history.messages
        guard let account = history.account, let target = history.selected?.target,
              page.loaded, page.loading == nil, page.failure == nil,
              let question = page.items.filter({ $0.role == "user" }).max(by: { $0.id < $1.id }),
              let answer = page.items.filter({ $0.role == "ai" }).max(by: { $0.id < $1.id }),
              answer.id > question.id, answer.attachments.isEmpty,
              [question, answer].allSatisfy({ supports($0, target: target) })
        else { return nil }
        do {
            let kind = try kind(question)
            guard try self.kind(answer) == kind else { return nil }
            if let originalID = answer.metadata?["user_message_id"] {
                guard case let .integer(id) = originalID, id == question.id else { return nil }
            }
            let metadata = question.metadata ?? [:]
            let quote = try optionalString(metadata["quote"])
            let source: Int64?
            switch metadata["quote_source_id"] {
            case nil, .null?: source = nil
            case let .integer(value)?: source = value
            default: return nil
            }
            let context = try ChatRequestContext(kind: kind, quoteText: quote, quoteSourceID: source,
                                                 attachmentIDs: attachments(question))
            try context.validate(input: question.content, target: target)
            return ChatRegeneration(account: account, target: target, answerID: answer.id,
                                    input: question.content, context: context)
        } catch { return nil }
    }

    static func rejected(_ error: HTTPFailure) -> Bool {
        switch error.code {
        case "CHAT_REGENERATE_INVALID", "CHAT_REGENERATE_NOT_LATEST": [400, 409].contains(error.status)
        case "CHAT_QUOTE_INVALID": error.status == 400
        case "ATTACHMENT_NOT_FOUND": error.status == 404
        case "ATTACHMENT_SCOPE_MISMATCH": error.status == 422
        default: false
        }
    }

    private static func kind(_ message: StoredChatMessage) throws -> ChatKind {
        guard let value = message.metadata?["kind"] else { return .qa }
        guard case let .string(text) = value, let kind = ChatKind(rawValue: text)
        else { throw ChatTurnFailure.invalidRequest }
        return kind
    }

    private static func optionalString(_ value: ChatJSONValue?) throws -> String? {
        switch value {
        case nil, .null?: nil
        case let .string(text)?: text
        default: throw ChatTurnFailure.invalidRequest
        }
    }

    private static func attachments(_ question: StoredChatMessage) throws -> [String] {
        let snapshots: [ChatJSONValue]
        if let value = question.metadata?["attachment_snapshot"] {
            guard case let .array(items) = value else { throw ChatTurnFailure.invalidRequest }
            snapshots = items
        } else {
            snapshots = []
        }
        guard snapshots.count <= 9,
              snapshots.count == question.attachments.count else { throw ChatTurnFailure.invalidRequest }
        return try zip(snapshots, question.attachments).map { snapshot, summary in
            guard case let .object(fields) = snapshot,
                  case let .string(id)? = fields["id"], case let .string(actualID)? = summary["id"],
                  id.utf8.elementsEqual(actualID.utf8),
                  case let .integer(revision)? = fields["revision"], revision > 0,
                  summary["revision"] == .integer(revision),
                  try coverage(fields) == coverage(summary)
            else { throw ChatTurnFailure.invalidRequest }
            return id
        }
    }

    private static func coverage(_ fields: [String: ChatJSONValue]) throws -> ChatJSONValue {
        guard let value = fields["accepted_coverage"] else { throw ChatTurnFailure.invalidRequest }
        switch value {
        case .null, .object: return value
        default: throw ChatTurnFailure.invalidRequest
        }
    }

    private static func supports(_ message: StoredChatMessage, target: ChatTarget) -> Bool {
        guard message.messageType == "chat", message.sessionID.utf8.elementsEqual(target.sessionID.utf8),
              message.nodeKey.utf8.elementsEqual(target.nodeKey.utf8), message.mode == target.mode.rawValue,
              (message.topicID ?? 0) == target.topicID
        else { return false }
        guard let status = message.metadata?["status"] else { return true }
        return ["complete", "failed", "interrupted"].map(ChatJSONValue.string).contains(status)
    }
}
