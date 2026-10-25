package com.gmaicoson.socraticmind.chat

/** Presentation of an authoritative outcome; never retries or changes turn ownership. */
internal object ChatTurnOutcome {
    fun notice(
        pending: PendingChatTurn,
        remote: RemoteChatTurn?,
        messages: List<StoredChatMessage>,
        rejectedModel: Boolean,
    ): String? {
        if (rejectedModel) return "所选模型不可用，请刷新模型目录或重新选择后发送；输入与原回答已保留。"
        if (remote == null) return "消息已更新或删除，请刷新历史查看。"
        val regeneration = pending.regenerateMessageId != null && remote.status != ChatTurnStatus.COMPLETE
        if (!regeneration && remote.ids != null && messages.size != 2) return "消息已更新或删除，请刷新历史查看。"
        if (remote.status == ChatTurnStatus.COMPLETE) return null
        val stored = messages.firstOrNull { it.role == "ai" && it.id == remote.ids?.ai }?.let(ChatAnswerFeedback::from)
        val feedback =
            ChatAnswerFeedback(
                remote.feedback?.usage ?: stored?.usage,
                remote.feedback?.failure ?: stored?.failure,
            )
        val fallback =
            if (remote.status == ChatTurnStatus.INTERRUPTED) {
                if (regeneration) "重新生成已停止，原回答仍保留。" else "回复已停止；已保存的部分可在历史中查看。"
            } else {
                if (regeneration) "重新生成失败，原回答仍保留。" else "本次回复失败；可查看已有内容后重新输入。"
            }
        val reason = feedback.failure?.message?.let { if (regeneration) "$it 原回答仍保留。" else it } ?: fallback
        return if (regeneration && (remote.feedback != null || stored?.usage != null)) {
            "$reason\n本次重生成：${feedback.usageSummary}\n${ChatAnswerFeedback.SCOPE_NOTE}"
        } else {
            reason
        }
    }
}
