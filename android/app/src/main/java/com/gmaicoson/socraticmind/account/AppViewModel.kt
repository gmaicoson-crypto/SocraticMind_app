package com.gmaicoson.socraticmind.account

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gmaicoson.socraticmind.AppGraph
import com.gmaicoson.socraticmind.auth.AuthFormController
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.auth.accountErrorMessage
import com.gmaicoson.socraticmind.chat.ChatActionsController
import com.gmaicoson.socraticmind.chat.ChatLibraryController
import com.gmaicoson.socraticmind.chat.ChatTarget
import com.gmaicoson.socraticmind.chat.ChatTurnController
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.UUID

class AppViewModel(
    result: Result<AppGraph>,
) : ViewModel() {
    private val graph = result.getOrNull()
    val configurationError = if (graph == null) "服务地址未正确配置，请检查当前开发配置。" else null
    val session = graph?.session?.state ?: MutableStateFlow<SessionState>(SessionState.Uninitialized).asStateFlow()
    val form = graph?.let { AuthFormController(it.session, it.auth) }
    val history = graph?.let { ChatLibraryController(it.session, it.history, viewModelScope) }
    val turn = graph?.let { ChatTurnController(it.session, it.turn, it.journal, viewModelScope) }
    val actions =
        graph?.let {
            ChatActionsController(it.session, it.actions, checkNotNull(history), checkNotNull(turn), viewModelScope)
        }
    private val mutableError = MutableStateFlow<String?>(null)
    val error = mutableError.asStateFlow()
    private var formJob: Job? = null
    private var sessionJob: Job? = null

    init {
        graph?.let {
            viewModelScope.launch {
                var accountRevision: Long? = null
                session.collect { state ->
                    history?.bindAccount(state)
                    turn?.bindAccount(state)
                    actions?.bindAccount(state)
                    val next = (state as? SessionState.SignedIn)?.revision
                    if (next != accountRevision) {
                        form?.reset()
                        accountRevision = next
                    }
                }
            }
            viewModelScope.launch {
                val coordinator = turn ?: return@launch
                coordinator.state.collect { state ->
                    val account = state.account
                    val library = history
                    if (account != null && library != null && library.state.value.account == account) {
                        state.pending?.let { pending -> library.openConversation(pending.target) }
                        state.receipt?.let { receipt ->
                            if (library.state.value.selected == null && state.target == receipt.pending.target) {
                                library.openConversation(receipt.pending.target)
                            }
                            library.accept(receipt, account)
                            coordinator.acknowledge(receipt)
                        }
                    }
                }
            }
            if (session.value == SessionState.Uninitialized) restore()
        }
    }

    fun submit() = runForm { form?.submit() }

    fun sendCode() = runForm { form?.sendCode() }

    private fun runForm(action: suspend () -> Unit) {
        if (formJob?.isActive == true || sessionJob?.isActive == true) return
        mutableError.value = null
        formJob = viewModelScope.launch { action() }
    }

    fun restore() = runSession { graph?.session?.restore() }

    fun newConversation() {
        val coordinator = turn ?: return
        if (!coordinator.state.value.editable) return
        val target = ChatTarget(UUID.randomUUID().toString())
        actions?.dismiss()
        coordinator.select(target)
        history?.openConversation(target)
    }

    fun selectConversation(id: String) {
        val coordinator = turn ?: return
        if (!coordinator.state.value.editable) return
        actions?.dismiss()
        history?.selectConversation(id)
        turn.select(
            history
                ?.state
                ?.value
                ?.selected
                ?.target,
        )
    }

    fun closeConversation() {
        val coordinator = turn ?: return
        if (!coordinator.state.value.editable) return
        actions?.dismiss()
        history?.closeConversation()
        coordinator.select(null)
    }

    fun logout() {
        if (sessionJob?.isActive == true) return
        formJob?.cancel()
        form?.reset()
        actions?.clear()
        history?.clear()
        turn?.clear()
        runSession { graph?.session?.logout() }
    }

    override fun onCleared() {
        actions?.close()
        history?.close()
        turn?.close()
        super.onCleared()
    }

    private fun runSession(action: suspend () -> Unit) {
        if (sessionJob?.isActive == true) return
        mutableError.value = null
        sessionJob =
            viewModelScope.launch {
                try {
                    action()
                } catch (error: Exception) {
                    if (error is CancellationException) throw error
                    if (session.value !is SessionState.SignedOut) mutableError.value = accountErrorMessage(error)
                }
            }
    }

    class Factory(
        private val graph: Result<AppGraph>,
    ) : ViewModelProvider.Factory {
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass == AppViewModel::class.java)
            @Suppress("UNCHECKED_CAST")
            return AppViewModel(graph) as T
        }
    }
}
