package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.auth.SessionStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Memory-only account selection. The turn owner snapshots it for each send and exposes it to suggestions. */
class ChatModelController(
    private val session: SessionStore,
    private val gateway: ChatModelGateway,
    private val turn: ChatTurnController,
    parentScope: CoroutineScope,
) {
    private val lock = Any()
    private val scope = CoroutineScope(parentScope.coroutineContext + SupervisorJob(parentScope.coroutineContext[Job]))
    private val mutableState = MutableStateFlow(ChatModelState())
    val state = mutableState.asStateFlow()
    private var job: Job? = null
    private var sequence = 0L
    private var closed = false

    fun bindAccount(value: SessionState): Unit =
        synchronized(lock) {
            val account = HistoryAccount.from(value)
            if (closed || account != HistoryAccount.from(session.state.value) || account == state.value.account) return
            clearLocked()
            if (account == null) return
            mutableState.value = ChatModelState(account = account)
            publishSelection()
            refresh()
        }

    fun select(
        id: String?,
        account: HistoryAccount,
    ): Unit =
        synchronized(lock) {
            if (!current() || state.value.account != account || !turn.state.value.editable ||
                turn.state.value.receipt != null
            ) {
                return
            }
            val option =
                id?.let { value ->
                    state.value.catalog
                        ?.models
                        ?.singleOrNull { it.id == value } ?: return
                }
            mutableState.value = state.value.copy(selected = option)
            publishSelection()
        }

    fun refresh(): Unit =
        synchronized(lock) {
            val account = state.value.account ?: return
            if (!current() || state.value.loading) return
            val ticket = ++sequence
            mutableState.value = state.value.copy(loading = true, notice = null)
            job =
                scope
                    .launch(start = CoroutineStart.LAZY) {
                        val result =
                            runCatching {
                                session.authenticated { token ->
                                    if (HistoryAccount.from(session.state.value) !=
                                        account
                                    ) {
                                        throw CancellationException()
                                    }
                                    gateway.catalog(token)
                                }
                            }
                        synchronized(lock) {
                            if (sequence != ticket) return@synchronized
                            if (!current()) {
                                clearLocked()
                                return@synchronized
                            }
                            job = null
                            val catalog = result.getOrNull()
                            mutableState.value =
                                if (catalog != null) {
                                    state.value.copy(
                                        catalog = catalog,
                                        selected =
                                            catalog.models.singleOrNull { it.id == state.value.selectedId }
                                                ?: state.value.selected,
                                        loading = false,
                                        notice = null,
                                    )
                                } else {
                                    state.value.copy(loading = false, notice = "模型目录暂不可用，请重试刷新；目录不代表模型调用可用。")
                                }
                            publishSelection()
                        }
                    }.also { it.start() }
        }

    fun clear() = synchronized(lock) { clearLocked() }

    fun close() {
        synchronized(lock) {
            closed = true
            clearLocked()
        }
        scope.cancel()
    }

    private fun publishSelection() {
        val value = state.value
        value.account?.let { turn.setModelSelection(it, value.selectedId, value.available) }
    }

    private fun current(): Boolean =
        !closed && state.value.account != null &&
            state.value.account == HistoryAccount.from(session.state.value) &&
            state.value.account == turn.state.value.account

    private fun clearLocked() {
        sequence++
        job?.cancel()
        job = null
        state.value.account?.let { turn.setModelSelection(it, null, true) }
        mutableState.value = ChatModelState()
    }
}
