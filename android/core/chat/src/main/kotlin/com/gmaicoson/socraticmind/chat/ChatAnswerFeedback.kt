package com.gmaicoson.socraticmind.chat

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/** Provider-reported tokens for one answer call, never an estimate or account balance. */
@ConsistentCopyVisibility
data class ReportedTokenUsage private constructor(
    val prompt: Long,
    val completion: Long,
    val total: Long,
) {
    init {
        require(listOf(prompt, completion, total).all { it in 0..9_007_199_254_740_991L })
        require(prompt + completion == total)
    }

    companion object {
        fun decode(value: JsonElement?): ReportedTokenUsage? {
            val fields = value as? JsonObject ?: return null
            val counts =
                listOf("prompt_tokens", "completion_tokens", "total_tokens").map { name ->
                    val number = fields[name] as? JsonPrimitive ?: return null
                    if (number.isString) return null
                    number.longOrNull?.takeIf { it in 0..9_007_199_254_740_991L } ?: return null
                }
            if (counts[0] + counts[1] != counts[2]) return null
            return ReportedTokenUsage(counts[0], counts[1], counts[2])
        }
    }
}

/** Only local descriptions reach UI; server messages and unknown codes are not retained. */
@ConsistentCopyVisibility
data class ChatModelFailure private constructor(
    val code: String,
    val message: String,
    val retryable: Boolean,
) {
    companion object {
        private val descriptions =
            mapOf(
                "AI_TIMEOUT" to ("等待模型回复超时，已保存的内容可在历史中查看；请稍后手动重试。" to true),
                "AI_RATE_LIMITED" to ("模型服务请求过于频繁，请稍后重试或切换模型。" to true),
                "AI_QUOTA_EXCEEDED" to ("模型服务额度不足，请检查服务配置或切换模型。" to false),
                "AI_PROVIDER_AUTH_FAILED" to ("模型服务凭据或权限不可用，请检查服务配置或切换模型。" to false),
                "AI_REQUEST_REJECTED" to ("模型服务未接受本次请求，请调整问题或切换模型。" to false),
                "AI_CONNECTION_FAILED" to ("与模型服务的连接中断，请查看已保存内容后手动重试。" to true),
                "AI_PROVIDER_UNAVAILABLE" to ("模型服务暂时不可用，请稍后重试或切换模型。" to true),
                "AI_BUSY" to ("当前生成请求较多，请稍后重试。" to true),
                "AI_OUTPUT_LIMIT" to ("回答达到模型输出长度上限，当前内容尚未完成；可调整问题后重试。" to false),
                "AI_STREAM_INCOMPLETE" to ("模型连接在回答完整结束前关闭，请查看已保存内容后手动重试。" to true),
                "AI_CONTENT_FILTERED" to ("模型服务中止了本次回答，请调整问题后重试。" to false),
                "AI_EMPTY_RESPONSE" to ("模型未返回可用回答，请重试或切换模型。" to true),
                "AI_UNEXPECTED_FINISH_REASON" to ("模型返回了不支持的结束状态，请重试或切换模型。" to false),
                "CHAT_CONTEXT_TOO_LARGE" to ("本次输入与上下文超过模型限制，请缩小范围后重试。" to false),
                "ATTACHMENT_CONTEXT_TIMEOUT" to ("资料处理或回答超时，请缩小范围后重试。" to true),
                "USER_CANCELLED" to ("本次生成已停止，已保存的内容可在历史中查看。" to false),
                "CLIENT_DISCONNECTED" to ("连接已断开，本次生成已停止；请查看已保存内容。" to true),
                "GENERATION_LEASE_EXPIRED" to ("此前生成未完整结束，请查看已保存内容后手动重试。" to true),
            )

        fun fromCode(value: String?): ChatModelFailure? {
            if (value == null) return null
            val description = descriptions[value]
            return if (description == null) {
                ChatModelFailure("AI_STREAM_ERROR", "本次回答未完成，请查看已有内容后手动重试。", true)
            } else {
                ChatModelFailure(value, description.first, description.second)
            }
        }
    }
}

data class ChatAnswerFeedback(
    val usage: ReportedTokenUsage?,
    val failure: ChatModelFailure?,
) {
    val usageSummary: String get() =
        usage?.let {
            "模型报告 token：输入 ${it.prompt} · 输出 ${it.completion} · 合计 ${it.total}"
        } ?: "用量未知：服务未提供有效报告。"

    companion object {
        const val SCOPE_NOTE = "仅本次回答，不含标题、摘要等其他调用；不代表费用或剩余额度。"

        fun decode(
            value: JsonObject,
            status: ChatTurnStatus?,
        ): ChatAnswerFeedback {
            fun code(
                source: JsonObject,
                key: String,
            ): String? = (source[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val errorCode = code(value, "error_code") ?: (value["error"] as? JsonObject)?.let { code(it, "code") }
            val failure =
                if (status == ChatTurnStatus.COMPLETE || status == ChatTurnStatus.GENERATING) {
                    null
                } else {
                    ChatModelFailure.fromCode(errorCode)
                }
            return ChatAnswerFeedback(ReportedTokenUsage.decode(value["usage"]), failure)
        }

        fun from(message: StoredChatMessage): ChatAnswerFeedback? {
            if (message.role != "ai") return null
            val metadata = message.metadata ?: JsonObject(emptyMap())
            val rawStatus = (metadata["status"] as? JsonPrimitive)?.content
            if (rawStatus in setOf("streaming", "generating", "superseded")) return null
            val feedback = decode(metadata, ChatTurnStatus.entries.firstOrNull { it.wireValue == rawStatus })
            return if (rawStatus in setOf("failed", "interrupted") && feedback.failure == null) {
                feedback.copy(failure = ChatModelFailure.fromCode("AI_STREAM_ERROR"))
            } else {
                feedback
            }
        }
    }
}
