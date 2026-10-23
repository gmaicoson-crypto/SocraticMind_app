package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionState

/** A revision changes even when the same user signs in again. No credentials enter UI state. */
data class HistoryAccount(
    val userId: Long,
    val revision: Long,
) {
    companion object {
        fun from(state: SessionState): HistoryAccount? =
            (state as? SessionState.SignedIn)?.let { HistoryAccount(it.user.id, it.revision) }
    }
}

enum class HistoryLoad { REFRESH, MORE }

data class HistoryLoadFailure(
    val operation: HistoryLoad,
    val message: String,
)

data class HistoryPageState<T>(
    val items: List<T> = emptyList(),
    val nextCursor: HistoryCursor? = null,
    val loaded: Boolean = false,
    val loading: HistoryLoad? = null,
    val failure: HistoryLoadFailure? = null,
) {
    internal fun <ID> accepting(
        page: ChatHistoryPage<T>,
        operation: HistoryLoad,
        identifier: (T) -> ID,
    ): HistoryPageState<T> {
        val combined = if (operation == HistoryLoad.REFRESH) page.items else items + page.items
        // A deletion can move a summary into a later page. Keep the newer version already loaded.
        return HistoryPageState(combined.distinctBy(identifier), page.nextCursor, loaded = true)
    }
}

data class ChatLibraryState(
    val account: HistoryAccount? = null,
    val conversations: HistoryPageState<ConversationSummary> = HistoryPageState(),
    val selected: ConversationSummary? = null,
    val messages: HistoryPageState<StoredChatMessage> = HistoryPageState(),
)
