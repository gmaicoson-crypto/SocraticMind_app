package com.gmaicoson.socraticmind.account

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gmaicoson.socraticmind.AppGraph
import com.gmaicoson.socraticmind.auth.AuthFormController
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.auth.accountErrorMessage
import com.gmaicoson.socraticmind.chat.ChatLibraryController
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class AppViewModel(
    result: Result<AppGraph>,
) : ViewModel() {
    private val graph = result.getOrNull()
    val configurationError = if (graph == null) "服务地址未正确配置，请检查当前开发配置。" else null
    val session = graph?.session?.state ?: MutableStateFlow<SessionState>(SessionState.Uninitialized).asStateFlow()
    val form = graph?.let { AuthFormController(it.session, it.auth) }
    val history = graph?.let { ChatLibraryController(it.session, it.history, viewModelScope) }
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
                    val next = (state as? SessionState.SignedIn)?.revision
                    if (next != accountRevision) {
                        form?.reset()
                        accountRevision = next
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

    fun logout() {
        if (sessionJob?.isActive == true) return
        formJob?.cancel()
        form?.reset()
        history?.clear()
        runSession { graph?.session?.logout() }
    }

    override fun onCleared() {
        history?.close()
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
