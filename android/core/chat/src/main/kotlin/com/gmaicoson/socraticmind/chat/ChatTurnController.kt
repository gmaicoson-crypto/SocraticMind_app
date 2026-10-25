package com.gmaicoson.socraticmind.chat

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
import kotlinx.coroutines.withTimeout
import java.util.UUID

/** One in-flight request per account. Cancelling local IO never asserts server cancellation. */
class ChatTurnController(
    private val session: SessionStore,
    private val gateway: ChatTurnGateway,
    private val journal: ChatTurnJournal,
    parentScope: CoroutineScope,
    private val requestId: () -> String = { UUID.randomUUID().toString() },
    private val pollDelays: List<Long> = listOf(500, 1000, 2000),
) {
    private val lock = Any()
    private val scope = CoroutineScope(parentScope.coroutineContext + SupervisorJob(parentScope.coroutineContext[Job]))
    private val mutableState = MutableStateFlow(ChatTurnState())
    val state = mutableState.asStateFlow()
    private var job: Job? = null
    private var ticket = 0L
    private var closed = false
    private var historyMutation: ChatMutationLease? = null

    internal fun reserveHistoryMutation(account: HistoryAccount): ChatMutationLease? =
        synchronized(lock) {
            if (!current() || state.value.account != account || !state.value.editable ||
                state.value.receipt != null
            ) {
                return null
            }
            ChatMutationLease(account).also {
                historyMutation = it
                mutableState.value = state.value.copy(changingHistory = true)
            }
        }

    internal fun releaseHistoryMutation(
        lease: ChatMutationLease,
        deletedSessionId: String? = null,
    ) = synchronized(lock) {
        if (historyMutation != lease) return@synchronized
        historyMutation = null
        if (!current()) return@synchronized
        val value = state.value
        mutableState.value =
            if (deletedSessionId != null && value.target?.sessionId == deletedSessionId) {
                value.copy(changingHistory = false, target = null, draft = "", notice = null)
            } else {
                value.copy(changingHistory = false)
            }
    }

    fun bindAccount(value: SessionState): Unit =
        synchronized(lock) {
            val account = HistoryAccount.from(value)
            if (closed || account != HistoryAccount.from(session.state.value) || account == state.value.account) return
            clearLocked()
            if (account == null) return
            mutableState.value = ChatTurnState(account = account)
            launchOperation { restore(it) }
        }

    fun clear() = synchronized(lock) { clearLocked() }

    fun close() {
        synchronized(lock) {
            closed = true
            clearLocked()
        }
        scope.cancel()
    }

    fun select(target: ChatTarget?): Unit =
        synchronized(lock) {
            if (!current() || !state.value.editable || state.value.target == target) return
            mutableState.value = state.value.copy(target = target, draft = "", notice = null)
        }

    /** Keep completion until the history owner consumes it, even when observation skips intermediate states. */
    fun acknowledge(receipt: ChatTurnReceipt) =
        synchronized(lock) {
            if (current() && state.value.receipt == receipt) {
                mutableState.value = state.value.copy(receipt = null)
            }
        }

    fun edit(value: String) =
        synchronized(lock) {
            if (current() && state.value.editable) mutableState.value = state.value.copy(draft = value, notice = null)
        }

    /** Compare-and-send prevents a delayed suggestion tap from replacing a newer draft or target. */
    internal fun sendSuggestion(
        account: HistoryAccount,
        target: ChatTarget,
        text: String,
        style: String,
        expectedDraft: String,
    ): Boolean =
        synchronized(lock) {
            val value = state.value
            if (!current() || !value.canRegenerate || value.account != account || value.target != target ||
                value.draft != expectedDraft
            ) {
                return@synchronized false
            }
            if (runCatching {
                    ChatTurnRequest(
                        PendingChatTurn(account.userId, target, "suggestion-check"),
                        text,
                        style,
                    )
                }.isFailure
            ) {
                return@synchronized false
            }
            mutableState.value = value.copy(draft = text)
            start(style, null)
            val started = state.value.pending != null
            if (!started) mutableState.value = state.value.copy(draft = expectedDraft)
            started
        }

    fun send(style: String): Unit = start(style, null)

    fun regenerate(
        history: ChatLibraryState,
        style: String,
    ) {
        val candidate = ChatRegeneration.from(history) ?: return
        start(style, candidate)
    }

    private fun start(
        style: String,
        regeneration: ChatRegeneration?,
    ): Unit =
        synchronized(lock) {
            val value = state.value
            if (!current()) return
            if (regeneration == null) {
                if (!value.canSend) return
            } else if (!value.canRegenerate || regeneration.account != value.account ||
                regeneration.target != value.target
            ) {
                return
            }
            val request =
                runCatching {
                    ChatTurnRequest(
                        PendingChatTurn(
                            checkNotNull(value.account).userId,
                            checkNotNull(value.target),
                            requestId(),
                            regeneration?.answerId,
                        ),
                        regeneration?.input ?: value.draft,
                        style,
                        regeneration?.context ?: ChatRequestContext(),
                    )
                }.getOrElse {
                    mutableState.value = value.copy(notice = "输入或会话配置无效，请检查后重试。")
                    return
                }
            mutableState.value = value.copy(phase = ChatTurnPhase.PREPARING, pending = request.pending, receipt = null)
            launchOperation { operation ->
                try {
                    journal.save(request.pending)
                } catch (error: Exception) {
                    update(operation) {
                        it.copy(phase = ChatTurnPhase.STORAGE_FAILED, notice = "恢复记录保存失败，尚未发送。请重试读取。")
                    }
                    return@launchOperation
                }
                update(operation) {
                    it.copy(
                        phase = ChatTurnPhase.SENDING,
                        draft = if (regeneration == null) "" else it.draft,
                        submitted = request.input,
                        partial = "",
                        ids = null,
                    )
                }
                val buffer = ChatTurnBuffer()
                var published = 0L
                try {
                    withTimeout(300_000) {
                        authenticated(operation) { token ->
                            gateway.stream(token, request).collect { event ->
                                requireCurrent(operation)
                                buffer.accept(event)
                                val now = System.nanoTime()
                                if (now - published >= 50_000_000 || buffer.ids != state.value.ids) {
                                    update(operation) { it.copy(partial = buffer.content(), ids = buffer.ids) }
                                    published = now
                                }
                            }
                        }
                    }
                } catch (error: Exception) {
                    requireCurrent(operation)
                    if (regeneration != null && error is HttpFailure && ChatRegeneration.rejected(error)) {
                        // A rejected stale question has no turn; persist a stop tombstone before clearing recovery.
                        val remote = authenticated(operation) { gateway.cancel(it, request.pending) }
                        finish(operation, request.pending, remote)
                        update(operation) { it.copy(notice = "原问题或引用、附件已变化，请刷新历史后重试。") }
                        return@launchOperation
                    }
                    // A transport error, timeout or DONE is not a confirmed terminal result.
                }
                update(operation) { it.copy(partial = buffer.content(), ids = buffer.ids) }
                verify(operation, request.pending)
            }
        }

    fun verify(): Unit =
        synchronized(lock) {
            if (!current() || !state.value.canVerify) return
            val pending = state.value.pending
            if (state.value.phase == ChatTurnPhase.STORAGE_FAILED) {
                mutableState.value = state.value.copy(phase = ChatTurnPhase.RESTORING)
                launchOperation { restore(it) }
            } else if (pending != null) {
                mutableState.value = state.value.copy(phase = ChatTurnPhase.VERIFYING)
                launchOperation { verify(it, pending) }
            }
        }

    fun stop(): Unit =
        synchronized(lock) {
            if (!current() || !state.value.canStop) return
            val pending = checkNotNull(state.value.pending)
            mutableState.value = state.value.copy(phase = ChatTurnPhase.STOPPING, notice = "正在确认停止…")
            launchOperation { operation ->
                val remote = authenticated(operation) { gateway.cancel(it, pending) }
                finish(operation, pending, remote)
            }
        }

    private suspend fun restore(operation: Long) {
        val account = checkNotNull(state.value.account)
        val pending =
            try {
                journal.read(account.userId)
            } catch (error: Exception) {
                update(operation) { it.copy(phase = ChatTurnPhase.STORAGE_FAILED, notice = "无法读取恢复记录，请重试；当前禁止发送。") }
                return
            }
        update(operation) {
            it.copy(
                pending = pending,
                target = pending?.target ?: it.target,
                phase = if (pending == null) ChatTurnPhase.READY else ChatTurnPhase.VERIFYING,
                notice = null,
            )
        }
        if (pending != null) verify(operation, pending)
    }

    private suspend fun verify(
        operation: Long,
        pending: PendingChatTurn,
    ) {
        update(operation) { it.copy(phase = ChatTurnPhase.VERIFYING, notice = "正在核对服务端状态…") }
        for (attempt in 0..pollDelays.size) {
            val remote =
                try {
                    authenticated(operation) { gateway.status(it, pending) }
                } catch (error: HttpFailure) {
                    if (error.status != 409 || error.code != "CHAT_REQUEST_DELETED") throw error
                    finish(operation, pending, null)
                    return
                }
            if (remote.status.terminal) {
                finish(operation, pending, remote)
                return
            }
            if (attempt < pollDelays.size) delay(pollDelays[attempt])
        }
        update(operation) { it.copy(phase = ChatTurnPhase.UNRESOLVED, notice = "服务仍在处理，可稍后核对或停止。不会自动重发。") }
    }

    private suspend fun finish(
        operation: Long,
        pending: PendingChatTurn,
        remote: RemoteChatTurn?,
    ) {
        require(remote == null || remote.status.terminal)
        val ids = remote?.ids
        val messages =
            if (ids == null) {
                emptyList()
            } else {
                require(state.value.ids == null || state.value.ids == ids) { "Recovered message IDs changed" }
                require(ids.ai != pending.regenerateMessageId) { "Regeneration did not allocate a new answer" }
                authenticated(operation) { gateway.messages(it, pending, ids) }
            }
        requireCurrent(operation)
        try {
            journal.clear(pending)
        } catch (error: Exception) {
            update(operation) {
                it.copy(
                    phase = ChatTurnPhase.STORAGE_FAILED,
                    notice = "结果已确认，恢复记录清理失败，请重试读取。",
                    receipt = ChatTurnReceipt(pending, remote?.status, messages),
                )
            }
            return
        }
        val notice =
            when {
                pending.regenerateMessageId != null && remote?.status == ChatTurnStatus.INTERRUPTED -> {
                    "重新生成已停止，原回答仍保留。"
                }

                pending.regenerateMessageId != null && remote?.status == ChatTurnStatus.FAILED -> {
                    "重新生成失败，原回答仍保留。"
                }

                remote == null || (ids != null && messages.size != 2) -> {
                    "消息已更新或删除，请刷新历史查看。"
                }

                remote.status == ChatTurnStatus.COMPLETE -> {
                    null
                }

                remote.status == ChatTurnStatus.INTERRUPTED -> {
                    "回复已停止；已保存的部分可在历史中查看。"
                }

                else -> {
                    "本次回复失败；可查看已有内容后重新输入。"
                }
            }
        update(operation) {
            it.copy(
                phase = ChatTurnPhase.READY,
                pending = null,
                submitted = "",
                partial = "",
                ids = null,
                notice = notice,
                receipt = ChatTurnReceipt(pending, remote?.status, messages),
            )
        }
    }

    private fun launchOperation(block: suspend (Long) -> Unit) {
        job?.cancel()
        val operation = ++ticket
        job =
            scope
                .launch(start = CoroutineStart.LAZY) {
                    try {
                        block(operation)
                    } catch (error: Exception) {
                        synchronized(lock) {
                            if (ticket != operation) return@synchronized
                            if (!current()) {
                                clearLocked()
                                return@synchronized
                            }
                            if (error !is CancellationException) {
                                mutableState.value =
                                    state.value.copy(
                                        phase = ChatTurnPhase.UNRESOLVED,
                                        notice = "结果尚未确认，请检查连接后核对或再次停止。不会自动重发。",
                                    )
                            }
                        }
                    }
                }.also { it.start() }
    }

    private suspend fun <T> authenticated(
        operation: Long,
        action: suspend (String) -> T,
    ): T =
        session.authenticated { token ->
            requireCurrent(operation)
            action(token).also { requireCurrent(operation) }
        }

    private fun update(
        operation: Long,
        transform: (ChatTurnState) -> ChatTurnState,
    ) = synchronized(lock) {
        requireCurrent(operation)
        mutableState.value = transform(state.value)
    }

    private fun requireCurrent(operation: Long) =
        synchronized(lock) {
            if (ticket != operation || !current()) throw CancellationException("Superseded chat operation")
        }

    private fun current() =
        !closed && state.value.account != null && state.value.account == HistoryAccount.from(session.state.value)

    private fun clearLocked() {
        historyMutation = null
        ++ticket
        job?.cancel()
        job = null
        mutableState.value = ChatTurnState()
    }
}
