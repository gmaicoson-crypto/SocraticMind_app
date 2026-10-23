package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionException
import com.gmaicoson.socraticmind.auth.SessionFailure
import com.gmaicoson.socraticmind.auth.SessionStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/** Owns suggestions only; history, credentials and durable sends stay with their existing owners. */
class ChatSuggestionsController(
    private val session: SessionStore,
    private val gateway: ChatSuggestionsGateway,
    private val history: ChatLibraryController,
    private val turn: ChatTurnController,
    parentScope: CoroutineScope,
) {
    private val lock = Any()
    private val scope = CoroutineScope(parentScope.coroutineContext + SupervisorJob(parentScope.coroutineContext[Job]))
    private val mutableState = MutableStateFlow(ChatSuggestionsState())
    val state = mutableState.asStateFlow()
    private val cache = ChatSuggestionsCache()
    private var owner: HistoryAccount? = null
    private var model: String? = null
    private var active = false
    private var closed = false
    private var attempted = false
    private var sequence = 0L
    private var request: Job? = null

    init {
        scope.launch { combine(history.state, turn.state, session.state) { _, _, _ -> Unit }.collect { synchronize() } }
    }

    fun setActive(value: Boolean) =
        synchronized(lock) {
            active = value
            synchronizeLocked()
        }

    fun setModel(value: String?) =
        synchronized(lock) {
            model = value
            synchronizeLocked()
        }

    fun clear() =
        synchronized(lock) {
            cancelLocked()
            owner = null
            cache.clear()
            attempted = false
            mutableState.value = ChatSuggestionsState()
        }

    fun close() {
        synchronized(lock) {
            closed = true
            clear()
        }
        scope.cancel()
    }

    fun refresh() =
        synchronized(lock) {
            synchronizeLocked(autoLoad = false)
            if (!state.value.enabled || state.value.loading || state.value.choice != null) return@synchronized
            loadLocked(state.value.items)
        }

    fun choose(
        text: String,
        context: ChatSuggestionContext,
        style: String,
    ) = synchronized(lock) {
        synchronizeLocked(autoLoad = false)
        if (!state.value.enabled || state.value.context != context || text !in state.value.items) return@synchronized
        val draft = turn.state.value.draft
        if (draft.isNotEmpty()) {
            cancelLocked()
            mutableState.value = state.value.copy(choice = ChatSuggestionChoice(text, draft))
        } else {
            sendLocked(text, style, draft)
        }
    }

    fun cancelChoice() = synchronized(lock) { mutableState.value = state.value.copy(choice = null) }

    fun confirmChoice(style: String) =
        synchronized(lock) {
            synchronizeLocked(autoLoad = false)
            val choice = state.value.choice ?: return@synchronized
            if (state.value.enabled && choice.text in state.value.items && choice.draft == turn.state.value.draft) {
                sendLocked(choice.text, style, choice.draft)
            }
        }

    private fun sendLocked(
        text: String,
        style: String,
        draft: String,
    ) {
        val context = state.value.context ?: return
        if (turn.sendSuggestion(context.account, context.target, text, style, draft)) {
            cancelLocked()
            mutableState.value = state.value.copy(enabled = false, choice = null)
        }
    }

    private fun synchronize() = synchronized(lock) { synchronizeLocked() }

    private fun synchronizeLocked(autoLoad: Boolean = true) {
        if (closed) return
        val h = history.state.value
        val t = turn.state.value
        val account = h.account?.takeIf { it == HistoryAccount.from(session.state.value) }
        if (account != owner) {
            cancelLocked()
            cache.clear()
            owner = account
            mutableState.value = ChatSuggestionsState()
            attempted = false
        }
        val context = if (account != null) ChatSuggestionContext.from(h, t, model) else null
        val enabled = active && context != null && t.editable && t.receipt == null && h.messages.loading == null
        if (context != state.value.context) {
            cancelLocked()
            attempted = false
            mutableState.value =
                ChatSuggestionsState(
                    context = context,
                    items = context?.let { ChatSuggestionDefaults.items(it) } ?: emptyList(),
                )
        }
        if (!enabled) cancelLocked()
        val choice = state.value.choice?.takeIf { enabled && it.draft == t.draft }
        mutableState.value = state.value.copy(enabled = enabled, choice = choice)
        if (autoLoad && enabled && !attempted && state.value.choice == null &&
            (context.hasConversation || (context.target.mode == ChatMode.SOCRATIC && context.target.topicId > 0))
        ) {
            val saved = cache.get(context)
            if (saved != null) {
                attempted = true
                mutableState.value = state.value.copy(items = saved.items, source = saved.source)
            } else {
                loadLocked(emptyList())
            }
        }
    }

    private fun cancelLocked() {
        sequence++
        request?.cancel()
        request = null
        if (state.value.loading) attempted = false
        mutableState.value = state.value.copy(loading = false)
    }

    private fun loadLocked(excluded: List<String>) {
        val context = state.value.context ?: return
        cancelLocked()
        attempted = true
        val ticket = ++sequence
        mutableState.value = state.value.copy(loading = true, notice = null, choice = null)
        val task =
            scope.launch(start = CoroutineStart.LAZY) {
                val response =
                    runCatching {
                        session.authenticated { token ->
                            if (HistoryAccount.from(session.state.value) !=
                                context.account
                            ) {
                                throw SessionException(SessionFailure.SUPERSEDED)
                            }
                            gateway.suggestions(token, context.target, excluded, context.model)
                        }
                    }
                synchronized(lock) {
                    synchronizeLocked()
                    if (sequence != ticket || state.value.context != context) return@synchronized
                    request = null
                    if (HistoryAccount.from(session.state.value) != context.account) {
                        clear()
                        return@synchronized
                    }
                    val failure = response.exceptionOrNull()
                    if (failure is CancellationException) {
                        mutableState.value = state.value.copy(loading = false)
                        attempted = false
                        return@synchronized
                    }
                    val result = response.getOrNull()
                    val fresh = result?.items?.filterNot { it in excluded }.orEmpty()
                    val items = if (fresh.isNotEmpty()) fresh else ChatSuggestionDefaults.items(context, excluded)
                    val source = if (fresh.isNotEmpty()) checkNotNull(result).source else SuggestionSource.LOCAL
                    val notice =
                        when {
                            failure != null -> "建议服务暂不可用，已显示参考话题。"
                            fresh.isEmpty() -> "没有更多建议，已显示参考话题。"
                            else -> null
                        }
                    val accepted = ChatSuggestions(items, source)
                    cache.put(context, accepted)
                    mutableState.value =
                        state.value.copy(items = items, source = source, loading = false, notice = notice)
                }
            }
        request = task
        task.start()
    }
}
