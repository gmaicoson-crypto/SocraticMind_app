package com.gmaicoson.socraticmind.chat

/** Read-only capability shared by history refresh and explicit title reads. */
interface ChatTitlesGateway {
    suspend fun titles(
        token: String,
        sessionIds: List<String>,
    ): List<ChatTitle>
}

internal fun ChatLibraryState.titleCandidates(newerPageFirst: Boolean): List<String> {
    val items = if (newerPageFirst) conversations.items.asReversed() else conversations.items
    val candidates = items.filter { it.titleStatus !in setOf("ready", "manual") }.map { it.sessionId }
    val opened = selected?.sessionId
    val priority =
        listOfNotNull(opened).filter { id ->
            id in candidates || items.none { it.sessionId == id }
        }
    return (priority + candidates).distinct().take(100)
}

internal fun ChatLibraryState.withTitles(titles: List<ChatTitle>): ChatLibraryState {
    val byId = titles.associateBy { it.sessionId }
    val rows =
        conversations.items.map { row ->
            byId[row.sessionId]?.let { row.copy(title = it.title, titleStatus = it.status.wireValue) } ?: row
        }
    val current = selected
    val title = current?.let { byId[it.sessionId] }
    return copy(
        conversations = conversations.copy(items = rows),
        selected = if (current != null && title != null) current.copy(title = title.title) else current,
    )
}

internal val ChatTitle.awaitingGeneration: Boolean
    get() =
        status == ChatTitleStatus.PENDING || status == ChatTitleStatus.RUNNING ||
            (status == ChatTitleStatus.FAILED && retryPending)
