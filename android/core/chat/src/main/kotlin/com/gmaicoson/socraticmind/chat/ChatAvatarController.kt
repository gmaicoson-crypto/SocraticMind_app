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
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Owns local selection and finite writes; the turn coordinator owns the shared mutation lease. */
class ChatAvatarController(
    private val session: SessionStore,
    private val gateway: ChatAvatarGateway,
    private val store: ChatAvatarStore,
    private val library: ChatLibraryController,
    private val turn: ChatTurnController,
    parentScope: CoroutineScope,
) {
    private val lock = Any()
    private val scope = CoroutineScope(parentScope.coroutineContext + SupervisorJob(parentScope.coroutineContext[Job]))
    private val mutableState = MutableStateFlow(ChatAvatarState())
    val state = mutableState.asStateFlow()
    private var job: Job? = null
    private var lease: ChatMutationLease? = null
    private var sequence = 0L
    private var closed = false

    fun bindAccount(value: SessionState): Unit =
        synchronized(lock) {
            val account = HistoryAccount.from(value)
            if (closed || account != HistoryAccount.from(session.state.value) || state.value.account == account) return
            clearLocked()
            if (account != null) {
                mutableState.value = ChatAvatarState(account = account)
                reload()
            }
        }

    fun clear() = synchronized(lock) { clearLocked() }

    fun close() {
        synchronized(lock) {
            closed = true
            clearLocked()
        }
        scope.cancel()
    }

    fun reload(): Unit =
        synchronized(lock) {
            val account = state.value.account ?: return
            if (!current() || state.value.busy || state.value.loading || state.value.pendingSave != null) return
            val ticket = ++sequence
            mutableState.value = state.value.copy(loading = true, notice = null)
            job =
                scope.launch {
                    val result = runCatching { store.read(account.userId) }
                    synchronized(lock) {
                        if (sequence != ticket) return@synchronized
                        if (!current()) {
                            clearLocked()
                            return@synchronized
                        }
                        job = null
                        mutableState.value =
                            result.fold(
                                { state.value.copy(choices = it, loaded = true, loading = false) },
                                { state.value.copy(loaded = false, loading = false, notice = "头像记录读取失败，请重试读取。") },
                            )
                    }
                }
        }

    fun open(target: ChatTarget): Unit =
        synchronized(lock) {
            if (!available() || !known(target)) return
            mutableState.value =
                state.value.copy(
                    picker = ChatAvatarPicker(checkNotNull(state.value.account), target),
                    notice = null,
                )
        }

    fun dismiss() =
        synchronized(lock) {
            if (!state.value.busy) mutableState.value = state.value.copy(picker = null)
        }

    fun selectPreset(
        picker: ChatAvatarPicker,
        resource: ChatAvatarResource?,
    ) {
        if (resource != null && resource.path !in ChatAvatarResource.presets(picker.target.mode)) return
        change(picker) { expected -> ChatAvatarSave(picker.target, expected, resource, clearRemote = true) }
    }

    fun upload(
        picker: ChatAvatarPicker,
        bytes: ByteArray,
        format: AvatarImageFormat,
    ) {
        if (bytes.isEmpty() || bytes.size > ChatAvatarResource.MAXIMUM_IMAGE_BYTES) {
            synchronized(lock) {
                if (state.value.picker == picker && current() && !state.value.busy) {
                    mutableState.value = state.value.copy(notice = "请选择不超过 5 MiB 的有效图片。")
                }
            }
            return
        }
        val snapshot = bytes.copyOf()
        change(picker) { expected ->
            val resource =
                authenticated(picker.account) {
                    gateway.upload(it, picker.account.userId, picker.target.sessionId, snapshot, format)
                }
            require(resource.uploaded && resource.belongsTo(picker.account.userId, picker.target.sessionId))
            ChatAvatarSave(picker.target, expected, resource, clearRemote = false)
        }
    }

    fun retrySave(): Unit =
        synchronized(lock) {
            val save = state.value.pendingSave ?: return
            val account = state.value.account ?: return
            start(account, retry = true) { save }
        }

    /** Explicitly abandon only the in-memory save; never issue another upload or delete. */
    fun discardPendingSave(): Unit =
        synchronized(lock) {
            if (!current() || state.value.busy || state.value.pendingSave == null) return
            mutableState.value = state.value.copy(pendingSave = null, picker = null)
            reload()
        }

    /** Called only after a confirmed session deletion, while actions holds the turn lease. */
    suspend fun forgetDeletedSession(
        account: HistoryAccount,
        sessionId: String,
    ): String? {
        val ticket =
            synchronized(lock) {
                if (!current() || state.value.account != account) return null
                job?.cancel()
                job = null
                mutableState.value = state.value.copy(loading = false, busy = true)
                ++sequence
            }
        val result =
            runCatching {
                val previous = store.read(account.userId)
                ensureAccount(account)
                store.replace(account.userId, sessionId, previous[sessionId], null)
                previous - sessionId
            }
        return synchronized(lock) {
            if (sequence != ticket || !current() || state.value.account != account) return@synchronized null
            val message = if (result.isFailure) "对话已删除，头像本地记录清理失败。" else null
            val value = state.value
            mutableState.value =
                value.copy(
                    choices = result.getOrNull() ?: (value.choices - sessionId),
                    loaded = result.isSuccess || value.loaded,
                    busy = false,
                    picker = value.picker?.takeUnless { it.target.sessionId == sessionId },
                    pendingSave = value.pendingSave?.takeUnless { it.target.sessionId == sessionId },
                    notice = message,
                )
            message
        }
    }

    private fun change(
        picker: ChatAvatarPicker,
        prepare: suspend (ChatAvatarResource?) -> ChatAvatarSave,
    ): Unit =
        synchronized(lock) {
            if (!available() || state.value.picker != picker || !known(picker.target)) return
            val expected = state.value.choices[picker.target.sessionId]
            start(picker.account, retry = false) { prepare(expected) }
        }

    private fun start(
        account: HistoryAccount,
        retry: Boolean,
        prepare: suspend () -> ChatAvatarSave,
    ) {
        if (!current() || state.value.busy || state.value.loading || !state.value.loaded ||
            state.value.account != account || (!retry && state.value.pendingSave != null)
        ) {
            return
        }
        val reservation = turn.reserveHistoryMutation(account) ?: return
        lease = reservation
        val ticket = ++sequence
        mutableState.value = state.value.copy(busy = true, notice = null)
        job =
            scope
                .launch(start = CoroutineStart.LAZY) {
                    var save: ChatAvatarSave? = null
                    var stored = false
                    val result =
                        runCatching {
                            ensureAccount(account)
                            val next = prepare()
                            ensureAccount(account)
                            save = next
                            val actual = store.read(account.userId)[next.target.sessionId]
                            ensureAccount(account)
                            if (actual != next.value) {
                                store.replace(account.userId, next.target.sessionId, next.expected, next.value)
                            }
                            stored = true
                            ensureAccount(account)
                            if (next.clearRemote) authenticated(account) { gateway.delete(it, next.target.sessionId) }
                        }
                    synchronized(lock) {
                        if (sequence != ticket) return@synchronized
                        turn.releaseHistoryMutation(reservation)
                        lease = null
                        job = null
                        if (!current()) {
                            clearLocked()
                            return@synchronized
                        }
                        val next = save
                        val value = state.value
                        mutableState.value =
                            when {
                                stored && next != null -> {
                                    value.copy(
                                        choices =
                                            if (next.value == null) {
                                                value.choices - next.target.sessionId
                                            } else {
                                                value.choices + (next.target.sessionId to next.value)
                                            },
                                        busy = false,
                                        pendingSave = null,
                                        picker = null,
                                        notice = if (result.isFailure) "头像已保存，但旧上传文件清理未确认。" else null,
                                    )
                                }

                                next != null -> {
                                    value.copy(
                                        busy = false,
                                        pendingSave = next,
                                        notice = "头像选择尚未保存。可重试保存或放弃；重试不会再次上传图片。",
                                    )
                                }

                                else -> {
                                    value.copy(busy = false, notice = uploadFailure(result.exceptionOrNull()))
                                }
                            }
                    }
                }.also { it.start() }
    }

    private suspend fun <T> authenticated(
        account: HistoryAccount,
        block: suspend (String) -> T,
    ): T =
        session.authenticated { token ->
            ensureAccount(account)
            block(token)
        }

    private suspend fun ensureAccount(account: HistoryAccount) {
        currentCoroutineContext().ensureActive()
        synchronized(lock) {
            if (!current() || state.value.account != account) throw SessionException(SessionFailure.SUPERSEDED)
        }
    }

    private fun available(): Boolean =
        current() && state.value.loaded && !state.value.loading &&
            !state.value.busy && state.value.pendingSave == null && turn.state.value.editable

    private fun known(target: ChatTarget): Boolean =
        library.state.value.selected
            ?.target == target

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
        mutableState.value = ChatAvatarState()
    }
}

private fun uploadFailure(error: Throwable?): String =
    when ((error as? HttpFailure)?.status) {
        400, 413, 415 -> "图片未被接受，请重新选择支持的图片。"
        429 -> "上传过于频繁，请稍后再试。"
        else -> "上传结果未确认，旧头像文件可能已被替换。请检查连接后重新选择；不会自动重传。"
    }
