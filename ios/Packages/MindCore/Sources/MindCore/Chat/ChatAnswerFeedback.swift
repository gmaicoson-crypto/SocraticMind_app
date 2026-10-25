import Foundation

/// Provider-reported tokens for one answer call, never an estimate or account balance.
public struct ReportedTokenUsage: Equatable, Sendable {
    public let prompt: Int64
    public let completion: Int64
    public let total: Int64

    public static func decode(_ value: ChatJSONValue?) -> ReportedTokenUsage? {
        guard case let .object(fields) = value else { return nil }
        func count(_ key: String) -> Int64? {
            guard case let .integer(number) = fields[key], (0 ... 9_007_199_254_740_991).contains(number) else {
                return nil
            }
            return number
        }
        guard let prompt = count("prompt_tokens"), let completion = count("completion_tokens"),
              let total = count("total_tokens"), prompt + completion == total else { return nil }
        return ReportedTokenUsage(prompt: prompt, completion: completion, total: total)
    }
}

/// Only local descriptions reach UI; server messages and unknown codes are not retained.
public struct ChatModelFailure: Equatable, Sendable {
    public let code: String
    public let message: String
    public let retryable: Bool

    private static let descriptions: [String: (String, Bool)] = [
        "AI_TIMEOUT": ("等待模型回复超时，已保存的内容可在历史中查看；请稍后手动重试。", true),
        "AI_RATE_LIMITED": ("模型服务请求过于频繁，请稍后重试或切换模型。", true),
        "AI_QUOTA_EXCEEDED": ("模型服务额度不足，请检查服务配置或切换模型。", false),
        "AI_PROVIDER_AUTH_FAILED": ("模型服务凭据或权限不可用，请检查服务配置或切换模型。", false),
        "AI_REQUEST_REJECTED": ("模型服务未接受本次请求，请调整问题或切换模型。", false),
        "AI_CONNECTION_FAILED": ("与模型服务的连接中断，请查看已保存内容后手动重试。", true),
        "AI_PROVIDER_UNAVAILABLE": ("模型服务暂时不可用，请稍后重试或切换模型。", true),
        "AI_BUSY": ("当前生成请求较多，请稍后重试。", true),
        "AI_OUTPUT_LIMIT": ("回答达到模型输出长度上限，当前内容尚未完成；可调整问题后重试。", false),
        "AI_STREAM_INCOMPLETE": ("模型连接在回答完整结束前关闭，请查看已保存内容后手动重试。", true),
        "AI_CONTENT_FILTERED": ("模型服务中止了本次回答，请调整问题后重试。", false),
        "AI_EMPTY_RESPONSE": ("模型未返回可用回答，请重试或切换模型。", true),
        "AI_UNEXPECTED_FINISH_REASON": ("模型返回了不支持的结束状态，请重试或切换模型。", false),
        "CHAT_CONTEXT_TOO_LARGE": ("本次输入与上下文超过模型限制，请缩小范围后重试。", false),
        "ATTACHMENT_CONTEXT_TIMEOUT": ("资料处理或回答超时，请缩小范围后重试。", true),
        "USER_CANCELLED": ("本次生成已停止，已保存的内容可在历史中查看。", false),
        "CLIENT_DISCONNECTED": ("连接已断开，本次生成已停止；请查看已保存内容。", true),
        "GENERATION_LEASE_EXPIRED": ("此前生成未完整结束，请查看已保存内容后手动重试。", true),
    ]

    public static func fromCode(_ value: String?) -> ChatModelFailure? {
        guard let value else { return nil }
        guard let description = descriptions[value] else {
            return ChatModelFailure(code: "AI_STREAM_ERROR", message: "本次回答未完成，请查看已有内容后手动重试。", retryable: true)
        }
        return ChatModelFailure(code: value, message: description.0, retryable: description.1)
    }
}

public struct ChatAnswerFeedback: Equatable, Sendable {
    public let usage: ReportedTokenUsage?
    public let failure: ChatModelFailure?

    public var usageSummary: String {
        guard let usage else { return "用量未知：服务未提供有效报告。" }
        return "模型报告 token：输入 \(usage.prompt) · 输出 \(usage.completion) · 合计 \(usage.total)"
    }

    public static let scopeNote = "仅本次回答，不含标题、摘要等其他调用；不代表费用或剩余额度。"

    public static func decode(_ value: [String: ChatJSONValue], status: ChatTurnStatus?) -> ChatAnswerFeedback {
        func code(_ fields: [String: ChatJSONValue], _ key: String) -> String? {
            guard case let .string(value) = fields[key] else { return nil }
            return value
        }
        var errorCode = code(value, "error_code")
        if errorCode == nil, case let .object(error) = value["error"] {
            errorCode = code(error, "code")
        }
        let failure = status == .complete || status == .generating ? nil : ChatModelFailure.fromCode(errorCode)
        return ChatAnswerFeedback(usage: ReportedTokenUsage.decode(value["usage"]), failure: failure)
    }

    public static func from(_ message: StoredChatMessage) -> ChatAnswerFeedback? {
        guard message.role == "ai" else { return nil }
        let metadata = message.metadata ?? [:]
        let rawStatus: String? = if case let .string(value) = metadata["status"] {
            value
        } else {
            nil
        }
        if let rawStatus, ["streaming", "generating", "superseded"].contains(rawStatus) {
            return nil
        }
        let feedback = decode(metadata, status: rawStatus.flatMap(ChatTurnStatus.init(rawValue:)))
        if let rawStatus, ["failed", "interrupted"].contains(rawStatus), feedback.failure == nil {
            return ChatAnswerFeedback(usage: feedback.usage, failure: ChatModelFailure.fromCode("AI_STREAM_ERROR"))
        }
        return feedback
    }
}
