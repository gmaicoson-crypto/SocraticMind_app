package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionException
import com.gmaicoson.socraticmind.auth.SessionFailure
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.auth.SessionStore
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** One account's finite history reads. The app binds session updates and owns this lifecycle. */
class ChatLibraryController(
    private val session: SessionStore,
    private val gateway: ChatHistoryGateway,
    parentScope: CoroutineScope,
    private val titles: ChatTitlesGateway,
    private val mode: ChatMode = ChatMode.NORMAL,
    private val titlePollDelays: List<Long> = listOf(500, 1000, 2000, 4000, 8000, 8000, 8000),
) {
    private enum class Lane { CONVERSATIONS, MESSAGES, TITLES }

    private data class Read(
        val ticket: Long,
        val job: Job,
    )

    private val lock = Any()
    private val scope = CoroutineScope(parentScope.coroutineContext + SupervisorJob(parentScope.coroutineContext[Job]))
    private val mutableState = MutableStateFlow(ChatLibraryState())
    val state = mutableState.asStateFlow()
    private val reads = mutableMapOf<Lane, Read>()
    private var sequence = 0L
    private var closed = false
    private var titlePollingActive = false

    init {
        require(titlePollDelays.size <= 7 && titlePollDelays.all { it in 0..8000 })
    }

    /** The visible app lifecycle activates reads; recomposition cannot restart an exhausted cycle. */
    fun setTitlePollingActive(active: Boolean) =
        synchronized(lock) {
            if (closed || titlePollingActive == active) return@synchronized
            titlePollingActive = active
            stopTitlesLocked()
            if (active) refreshTitlesLocked()
        }

    fun bindAccount(value: SessionState) {
        synchronized(lock) {
            val account = HistoryAccount.from(value)
            if (closed || account != HistoryAccount.from(session.state.value) || state.value.account == account) return
            clearLocked()
            mutableState.value = ChatLibraryState(account = account)
        }
        refreshConversations()
    }

    /** Clear synchronously on logout, before storage or observation can suspend. */
    fun clear() = synchronized(lock) { clearLocked() }

    fun close() {
        synchronized(lock) {
            closed = true
            clearLocked()
        }
        scope.cancel()
    }

    fun refreshConversations() = readConversations(HistoryLoad.REFRESH)

    fun loadMoreConversations() = readConversations(HistoryLoad.MORE)

    fun refreshMessages() = readMessages(HistoryLoad.REFRESH)

    fun refreshSelectedConversation() {
        refreshMessages()
        refreshConversations()
    }

    internal fun accept(
        change: ChatLibraryChange,
        account: HistoryAccount,
    ) {
        var refreshSelected = false
        synchronized(lock) {
            if (!isCurrentAccount() || state.value.account != account) return
            stopTitlesLocked()
            reads.remove(Lane.CONVERSATIONS)?.job?.cancel()
            if (state.value.selected?.sessionId == change.sessionId && change !is ChatLibraryChange.Renamed) {
                reads.remove(Lane.MESSAGES)?.job?.cancel()
                refreshSelected = change is ChatLibraryChange.DeletedMessages
            }
            mutableState.value = state.value.applying(change)
        }
        if (refreshSelected) refreshMessages()
        if (change !is ChatLibraryChange.Renamed) refreshConversations()
    }

    fun loadMoreMessages() = readMessages(HistoryLoad.MORE)

    fun selectConversation(sessionId: String) {
        synchronized(lock) {
            if (!isCurrentAccount() || state.value.selected?.sessionId == sessionId) return
            val summary =
                state.value.conversations.items
                    .find { it.sessionId == sessionId } ?: return
            val target =
                runCatching {
                    ChatTarget(summary.sessionId, mode, summary.nodeKey, summary.topicId ?: 0)
                }.getOrNull() ?: return
            reads.remove(Lane.MESSAGES)?.job?.cancel()
            mutableState.value =
                state.value.copy(selected = ChatConversation(target, summary.title), messages = HistoryPageState())
            stopTitlesLocked()
            refreshTitlesLocked()
        }
        refreshMessages()
    }

    fun openConversation(target: ChatTarget) {
        synchronized(lock) {
            if (!isCurrentAccount() || state.value.selected?.target == target || target.mode != mode) return
            reads.remove(Lane.MESSAGES)?.job?.cancel()
            mutableState.value = state.value.copy(selected = ChatConversation(target), messages = HistoryPageState())
        }
        refreshMessages()
    }

    /** Authoritative turn rows replace matching IDs; invalidate old reads before they can drop the new rows. */
    fun accept(
        receipt: ChatTurnReceipt,
        account: HistoryAccount,
    ) {
        var refresh = false
        synchronized(lock) {
            if (!isCurrentAccount() || state.value.account != account ||
                receipt.pending.ownerId != account.userId
            ) {
                return
            }
            if (state.value.selected?.target == receipt.pending.target) {
                reads.remove(Lane.MESSAGES)?.job?.cancel()
                val page = state.value.messages
                refresh = !page.loaded || receipt.messages.isEmpty() ||
                    (receipt.replacedMessageId != null && receipt.messages.none { it.role == "ai" })
                val items =
                    (receipt.historyMessages + page.items.filter(receipt::retains))
                        .distinctBy { it.id }
                        .sortedByDescending { it.id }
                mutableState.value =
                    state.value.copy(messages = page.copy(items = items, loaded = true, loading = null, failure = null))
            }
        }
        if (refresh) refreshMessages()
        refreshConversations()
    }

    fun closeConversation() =
        synchronized(lock) {
            reads.remove(Lane.MESSAGES)?.job?.cancel()
            mutableState.value = state.value.copy(selected = null, messages = HistoryPageState())
        }

    private fun readConversations(operation: HistoryLoad) =
        read(
            Lane.CONVERSATIONS,
            operation,
            { it.conversations },
            { value, page ->
                val current = value.selected
                val title = page.items.find { it.sessionId == current?.sessionId }
                value.copy(
                    conversations = page,
                    selected =
                        if (current != null &&
                            title != null
                        ) {
                            current.copy(title = title.title)
                        } else {
                            current
                        },
                )
            },
            { it.sessionId },
        ) { token, cursor -> gateway.conversations(token, mode, cursor = cursor) }

    private fun readMessages(operation: HistoryLoad) {
        synchronized(lock) {
            val selected = state.value.selected?.sessionId ?: return
            read(
                Lane.MESSAGES,
                operation,
                { it.messages },
                { value, page -> value.copy(messages = page) },
                { it.id },
            ) { token, cursor -> gateway.messages(token, selected, cursor = cursor) }
        }
    }

    private fun <T, ID> read(
        lane: Lane,
        operation: HistoryLoad,
        pageState: (ChatLibraryState) -> HistoryPageState<T>,
        update: (ChatLibraryState, HistoryPageState<T>) -> ChatLibraryState,
        identifier: (T) -> ID,
        request: suspend (String, HistoryCursor?) -> ChatHistoryPage<T>,
    ) {
        val job =
            synchronized(lock) {
                if (!isCurrentAccount()) return
                val account = checkNotNull(state.value.account)
                val page = pageState(state.value)
                if (page.loading == operation) return
                if (operation == HistoryLoad.MORE &&
                    (page.loading != null || !page.loaded || page.nextCursor == null)
                ) {
                    return
                }
                if (lane == Lane.CONVERSATIONS) stopTitlesLocked()
                reads.remove(lane)?.job?.cancel()
                val ticket = ++sequence
                val cursor = if (operation == HistoryLoad.MORE) page.nextCursor else null
                mutableState.value = update(state.value, page.copy(loading = operation, failure = null))
                val next =
                    scope.launch(start = CoroutineStart.LAZY) {
                        val result =
                            runCatching {
                                session.authenticated { token ->
                                    if (HistoryAccount.from(session.state.value) != account) {
                                        throw SessionException(SessionFailure.SUPERSEDED)
                                    }
                                    request(token, cursor)
                                }
                            }
                        synchronized(lock) finish@{
                            if (reads[lane]?.ticket != ticket || state.value.account != account) return@finish
                            reads.remove(lane)
                            if (!isCurrentAccount()) {
                                clearLocked()
                                return@finish
                            }
                            val current = pageState(state.value)
                            val finished =
                                result.fold(
                                    { current.accepting(it, operation, identifier) },
                                    { current.copy(loading = null, failure = historyFailure(operation, it)) },
                                )
                            mutableState.value = update(state.value, finished)
                            if (lane == Lane.CONVERSATIONS && result.isSuccess) {
                                refreshTitlesLocked(operation == HistoryLoad.MORE)
                            }
                        }
                    }
                reads[lane] = Read(ticket, next)
                next
            }
        job.start()
    }

    private fun stopTitlesLocked() {
        reads.remove(Lane.TITLES)?.job?.cancel()
        mutableState.value = state.value.copy(refreshingTitles = false, titleNotice = null)
    }

    private fun refreshTitlesLocked(newerPageFirst: Boolean = false) {
        if (!titlePollingActive || !isCurrentAccount() || state.value.conversations.loading != null ||
            reads[Lane.TITLES] != null
        ) {
            return
        }
        var ids = state.value.titleCandidates(newerPageFirst)
        if (ids.isEmpty()) return
        val account = checkNotNull(state.value.account)
        val ticket = ++sequence
        mutableState.value = state.value.copy(refreshingTitles = true, titleNotice = null)
        val task =
            scope.launch(start = CoroutineStart.LAZY) {
                var failed = false
                var notice: String? = null
                try {
                    for (pause in listOf(0L) + titlePollDelays) {
                        delay(pause)
                        val result =
                            session.authenticated { token ->
                                if (HistoryAccount.from(session.state.value) != account) {
                                    throw SessionException(SessionFailure.SUPERSEDED)
                                }
                                titles.titles(token, ids)
                            }
                        synchronized(lock) {
                            if (reads[Lane.TITLES]?.ticket != ticket || state.value.account != account) return@launch
                            if (!isCurrentAccount()) {
                                clearLocked()
                                return@launch
                            }
                            mutableState.value = state.value.withTitles(result)
                        }
                        failed = failed || result.any { it.status == ChatTitleStatus.FAILED && !it.retryPending }
                        ids = result.filter { it.awaitingGeneration }.map { it.sessionId }
                        if (ids.isEmpty()) break
                    }
                    notice =
                        when {
                            ids.isNotEmpty() -> "部分标题仍在生成，可稍后刷新。"
                            failed -> "部分自动标题生成失败，可手动命名或刷新。"
                            else -> null
                        }
                } catch (error: Exception) {
                    if (error !is CancellationException) notice = "标题更新失败，可稍后刷新。"
                }
                synchronized(lock) {
                    if (reads[Lane.TITLES]?.ticket != ticket || state.value.account != account) return@synchronized
                    reads.remove(Lane.TITLES)
                    if (!isCurrentAccount()) {
                        clearLocked()
                        return@synchronized
                    }
                    mutableState.value = state.value.copy(refreshingTitles = false, titleNotice = notice)
                }
            }
        reads[Lane.TITLES] = Read(ticket, task)
        task.start()
    }

    private fun isCurrentAccount() =
        !closed && state.value.account != null &&
            state.value.account == HistoryAccount.from(session.state.value)

    private fun clearLocked() {
        reads.values.forEach { it.job.cancel() }
        reads.clear()
        mutableState.value = ChatLibraryState()
    }
}

private fun historyFailure(
    operation: HistoryLoad,
    error: Throwable,
): HistoryLoadFailure? {
    if (error is CancellationException) return null
    val message =
        if (error is HttpFailure && error.status == 404) {
            "当前服务暂不支持会话读取，请更新服务后重试。"
        } else {
            "读取失败，请检查网络与服务后重试。"
        }
    return HistoryLoadFailure(operation, message)
}
