package com.gmaicoson.socraticmind.chat

import java.util.Collections

enum class ChatKind(
    val wireValue: String,
) {
    QA("qa"),
    TOPIC_OVERVIEW("topic_overview"),
    NODE_OVERVIEW("node_overview"),
}

/** An in-memory request snapshot. Recovery persists identifiers, never this context. */
class ChatRequestContext(
    val kind: ChatKind = ChatKind.QA,
    val quoteText: String? = null,
    val quoteSourceId: Long? = null,
    attachmentIds: List<String> = emptyList(),
) {
    val attachmentIds: List<String> = Collections.unmodifiableList(ArrayList(attachmentIds))

    init {
        require(quoteText == null || quoteText.codePointCount(0, quoteText.length) <= 200)
        require(quoteSourceId == null || (quoteSourceId > 0 && !quoteText.isNullOrEmpty()))
        require(this.attachmentIds.size <= 9 && this.attachmentIds.distinct().size == this.attachmentIds.size)
        require(this.attachmentIds.all { it.isNotEmpty() && it.codePointCount(0, it.length) <= 36 })
        require(kind == ChatKind.QA || this.attachmentIds.isEmpty())
    }

    internal fun validate(
        input: String,
        target: ChatTarget,
    ) {
        require(input.codePointCount(0, input.length) <= 5000)
        require(input.isNotBlank() || kind != ChatKind.QA || attachmentIds.isNotEmpty())
        require(kind == ChatKind.QA || (target.mode == ChatMode.SOCRATIC && target.topicId > 0))
    }
}
