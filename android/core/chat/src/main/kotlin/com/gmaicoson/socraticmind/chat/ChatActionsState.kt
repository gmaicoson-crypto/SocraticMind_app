package com.gmaicoson.socraticmind.chat

import java.util.UUID

sealed interface ChatAction {
    val sessionId: String

    data class Rename(
        override val sessionId: String,
        val title: String,
    ) : ChatAction

    data class DeleteSession(
        override val sessionId: String,
        val title: String,
        val discardsDraft: Boolean,
    ) : ChatAction

    data class DeleteMessages(
        override val sessionId: String,
        val ids: Set<Long>,
    ) : ChatAction
}

data class ChatActionsState(
    val account: HistoryAccount? = null,
    val dialog: ChatAction? = null,
    val busy: Boolean = false,
    val selectionSessionId: String? = null,
    val selectedIds: Set<Long> = emptySet(),
    val notice: String? = null,
) {
    val canConfirm: Boolean get() =
        !busy &&
            when (val action = dialog) {
                is ChatAction.Rename -> {
                    action.title.trim().let {
                        it.isNotEmpty() &&
                            it.codePointCount(0, it.length) <= 40
                    }
                }

                is ChatAction.DeleteSession -> {
                    true
                }

                is ChatAction.DeleteMessages -> {
                    action.ids.size in 1..100
                }

                null -> {
                    false
                }
            }
}

internal data class ChatMutationLease(
    val account: HistoryAccount,
    val id: UUID = UUID.randomUUID(),
)

internal sealed interface ChatLibraryChange {
    val sessionId: String

    data class Renamed(
        val title: ChatTitle,
    ) : ChatLibraryChange {
        override val sessionId get() = title.sessionId
    }

    data class DeletedSession(
        override val sessionId: String,
    ) : ChatLibraryChange

    data class DeletedMessages(
        override val sessionId: String,
        val ids: Set<Long>,
    ) : ChatLibraryChange
}

/** Projection only; the library owns cancellation and its authoritative refresh. */
internal fun ChatLibraryState.applying(change: ChatLibraryChange): ChatLibraryState {
    val summaries =
        when (change) {
            is ChatLibraryChange.Renamed -> {
                conversations.items.map {
                    if (it.sessionId ==
                        change.sessionId
                    ) {
                        it.copy(title = change.title.title, titleStatus = change.title.status.wireValue)
                    } else {
                        it
                    }
                }
            }

            else -> {
                conversations.items.filterNot { it.sessionId == change.sessionId }
            }
        }
    var next = copy(conversations = conversations.copy(items = summaries, loading = null, failure = null))
    if (selected?.sessionId != change.sessionId) return next
    next =
        when (change) {
            is ChatLibraryChange.Renamed -> {
                next.copy(selected = selected.copy(title = change.title.title))
            }

            is ChatLibraryChange.DeletedSession -> {
                next.copy(selected = null, messages = HistoryPageState())
            }

            is ChatLibraryChange.DeletedMessages -> {
                next.copy(
                    messages =
                        messages.copy(
                            items = messages.items.filterNot { it.id in change.ids },
                            loading = null,
                            failure = null,
                        ),
                )
            }
        }
    return next
}
