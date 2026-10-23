package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionException
import com.gmaicoson.socraticmind.auth.SessionFailure
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.auth.SessionStore
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Owns finite user-confirmed mutations; history and sending keep their existing state ownership. */
class ChatActionsController(
    private val session: SessionStore,
    private val gateway: ChatActionsGateway,
    private val library: ChatLibraryController,
    private val turn: ChatTurnController,
    parentScope: CoroutineScope,
) {
    private val lock = Any()
    private val scope = CoroutineScope(parentScope.coroutineContext + SupervisorJob(parentScope.coroutineContext[Job]))
    private val mutableState = MutableStateFlow(ChatActionsState())
    val state = mutableState.asStateFlow()
    private var job: Job? = null
    private var lease: ChatMutationLease? = null
    private var sequence = 0L
    private var closed = false

    fun bindAccount(value: SessionState) =
        synchronized(lock) {
            val account = HistoryAccount.from(value)
            if (closed || account != HistoryAccount.from(session.state.value) ||
                state.value.account == account
            ) {
                return@synchronized
            }
            clearLocked()
            mutableState.value = ChatActionsState(account = account)
        }

    fun clear() = synchronized(lock) { clearLocked() }

    fun close() {
        synchronized(lock) {
            closed = true
            clearLocked()
        }
        scope.cancel()
    }

    fun canManage(sessionId: String): Boolean =
        synchronized(lock) {
            current() && !state.value.busy && turn.state.value.editable && knownSession(sessionId)
        }

    fun rename(sessionId: String) =
        synchronized(lock) {
            if (!canManage(sessionId)) return@synchronized
            mutableState.value =
                state.value.copy(dialog = ChatAction.Rename(sessionId, title(sessionId)), notice = null)
        }

    fun deleteSession(sessionId: String) =
        synchronized(lock) {
            if (!canManage(sessionId)) return@synchronized
            val value = turn.state.value
            mutableState.value =
                state.value.copy(
                    dialog =
                        ChatAction.DeleteSession(
                            sessionId,
                            title(sessionId),
                            value.target?.sessionId == sessionId && value.draft.isNotEmpty(),
                        ),
                    notice = null,
                )
        }

    fun editTitle(value: String) =
        synchronized(lock) {
            val dialog = state.value.dialog as? ChatAction.Rename ?: return@synchronized
            if (!current() || state.value.busy) return@synchronized
            mutableState.value = state.value.copy(dialog = dialog.copy(title = value), notice = null)
        }

    fun selectMessages() =
        synchronized(lock) {
            val selected =
                library.state.value.selected
                    ?.sessionId ?: return@synchronized
            if (!canManage(selected)) return@synchronized
            mutableState.value =
                state.value.copy(selectionSessionId = selected, selectedIds = emptySet(), dialog = null, notice = null)
        }

    fun toggleMessage(id: Long) =
        synchronized(lock) {
            val value = state.value
            if (!current() || value.busy || !turn.state.value.editable ||
                value.selectionSessionId == null || value.selectionSessionId !=
                library.state.value.selected
                    ?.sessionId ||
                library.state.value.messages.items
                    .none { it.id == id }
            ) {
                return@synchronized
            }
            val selected = value.selectedIds
            if (id !in selected && selected.size >= 100) {
                mutableState.value = value.copy(notice = "一次最多选择 100 条消息。")
                return@synchronized
            }
            mutableState.value =
                value.copy(selectedIds = if (id in selected) selected - id else selected + id, notice = null)
        }

    fun deleteSelectedMessages() =
        synchronized(lock) {
            val value = state.value
            val selected = value.selectionSessionId ?: return@synchronized
            if (!canManage(selected) || selected !=
                library.state.value.selected
                    ?.sessionId
            ) {
                return@synchronized
            }
            val available =
                library.state.value.messages.items
                    .map { it.id }
                    .toSet()
            val ids = value.selectedIds.intersect(available)
            mutableState.value =
                value.copy(
                    selectedIds = ids,
                    dialog = if (ids.isEmpty()) null else ChatAction.DeleteMessages(selected, ids),
                    notice = null,
                )
        }

    fun cancelDialog() =
        synchronized(lock) {
            if (!state.value.busy) mutableState.value = state.value.copy(dialog = null, notice = null)
        }

    fun dismiss() =
        synchronized(lock) {
            if (!state.value.busy) mutableState.value = ChatActionsState(account = state.value.account)
        }

    fun confirm() {
        val next =
            synchronized(lock) {
                val value = state.value
                val action = value.dialog ?: return
                val account = value.account ?: return
                if (!current() || !value.canConfirm) return
                if (!valid(action)) {
                    mutableState.value = value.copy(notice = "会话内容已变化，请刷新后重新选择。")
                    return
                }
                val reservation = turn.reserveHistoryMutation(account)
                if (reservation == null) {
                    mutableState.value = value.copy(notice = "请先等待或处理当前回答，再修改会话。")
                    return
                }
                lease = reservation
                val ticket = ++sequence
                mutableState.value = value.copy(busy = true, notice = null)
                scope
                    .launch(start = CoroutineStart.LAZY) {
                        val result =
                            runCatching {
                                session.authenticated { token ->
                                    if (HistoryAccount.from(session.state.value) !=
                                        account
                                    ) {
                                        throw SessionException(SessionFailure.SUPERSEDED)
                                    }
                                    perform(token, action)
                                }
                            }
                        synchronized(lock) finish@{
                            if (ticket != sequence) return@finish
                            if (!current()) {
                                clearLocked()
                                return@finish
                            }
                            job = null
                            result.fold(
                                { change ->
                                    library.accept(change, account)
                                    turn.releaseHistoryMutation(
                                        reservation,
                                        (change as? ChatLibraryChange.DeletedSession)?.sessionId,
                                    )
                                    mutableState.value = ChatActionsState(account = account)
                                },
                                { error ->
                                    turn.releaseHistoryMutation(reservation)
                                    mutableState.value = state.value.copy(busy = false, notice = actionFailure(error))
                                },
                            )
                            lease = null
                        }
                    }.also { job = it }
            }
        next.start()
    }

    private suspend fun perform(
        token: String,
        action: ChatAction,
    ): ChatLibraryChange =
        when (action) {
            is ChatAction.Rename -> {
                ChatLibraryChange.Renamed(gateway.rename(token, action.sessionId, action.title))
            }

            is ChatAction.DeleteSession -> {
                gateway.deleteSession(token, action.sessionId)
                ChatLibraryChange.DeletedSession(action.sessionId)
            }

            is ChatAction.DeleteMessages -> {
                gateway.deleteMessages(token, action.ids.sorted())
                ChatLibraryChange.DeletedMessages(action.sessionId, action.ids)
            }
        }

    private fun valid(action: ChatAction): Boolean {
        if (!knownSession(action.sessionId)) return false
        if (action !is ChatAction.DeleteMessages) return true
        return library.state.value.selected
            ?.sessionId == action.sessionId &&
            action.ids.all { id ->
                library.state.value.messages.items
                    .any { it.id == id }
            }
    }

    private fun knownSession(id: String): Boolean =
        library.state.value.let {
            it.conversations.items.any { row -> row.sessionId == id } ||
                (it.selected?.sessionId == id && it.messages.items.isNotEmpty())
        }

    private fun title(id: String): String =
        library.state.value.let {
            it.conversations.items
                .find { row -> row.sessionId == id }
                ?.title
                ?: it.selected?.takeIf { row -> row.sessionId == id }?.title
                ?: ""
        }

    private fun current(): Boolean =
        !closed && state.value.account != null &&
            state.value.account == HistoryAccount.from(session.state.value) &&
            state.value.account == library.state.value.account && state.value.account == turn.state.value.account

    private fun clearLocked() {
        ++sequence
        job?.cancel()
        job = null
        lease?.let { turn.releaseHistoryMutation(it) }
        lease = null
        mutableState.value = ChatActionsState()
    }
}

private fun actionFailure(error: Throwable): String =
    when ((error as? HttpFailure)?.status) {
        404 -> "对话不存在或已删除，请刷新后重试。"
        405 -> "当前服务暂不支持此操作，请更新服务后重试。"
        else -> "操作结果未确认，请检查连接并刷新核对后重试。"
    }
