package com.gmaicoson.socraticmind.account

import android.graphics.Bitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.gmaicoson.socraticmind.AppGraph
import com.gmaicoson.socraticmind.auth.AuthFormController
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.auth.accountErrorMessage
import com.gmaicoson.socraticmind.avatarui.AvatarImageCodec
import com.gmaicoson.socraticmind.chat.ChatActionsController
import com.gmaicoson.socraticmind.chat.ChatAvatarController
import com.gmaicoson.socraticmind.chat.ChatLibraryController
import com.gmaicoson.socraticmind.chat.ChatSuggestionsController
import com.gmaicoson.socraticmind.chat.ChatTarget
import com.gmaicoson.socraticmind.chat.ChatTurnController
import com.gmaicoson.socraticmind.chat.HistoryAccount
import com.gmaicoson.socraticmind.chat.images.AvatarImageLoader
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
    val history = graph?.let { ChatLibraryController(it.session, it.history, viewModelScope, it.actions) }
    val turn = graph?.let { ChatTurnController(it.session, it.turn, it.journal, viewModelScope) }
    val avatars =
        graph?.let {
            ChatAvatarController(
                it.session,
                it.avatars,
                it.avatarStore,
                checkNotNull(history),
                checkNotNull(turn),
                viewModelScope,
            )
        }
    val actions =
        graph?.let {
            ChatActionsController(
                it.session,
                it.actions,
                checkNotNull(history),
                checkNotNull(turn),
                viewModelScope,
            ) { account, id ->
                avatars?.forgetDeletedSession(account, id)
            }
        }
    val suggestions =
        graph?.let {
            ChatSuggestionsController(
                it.session,
                it.suggestions,
                checkNotNull(history),
                checkNotNull(turn),
                viewModelScope,
            )
        }
    private val mutableError = MutableStateFlow<String?>(null)
    private val mutableAvatarImages = MutableStateFlow<AvatarImageLoader<Bitmap>?>(null)
    val avatarImages = mutableAvatarImages.asStateFlow()
    val error = mutableError.asStateFlow()
    private var formJob: Job? = null
    private var sessionJob: Job? = null

    init {
        graph?.let {
            viewModelScope.launch {
                var accountRevision: Long? = null
                session.collect { state ->
                    val imageAccount = HistoryAccount.from(state)
                    if (mutableAvatarImages.value?.account != imageAccount) {
                        mutableAvatarImages.value?.close()
                        mutableAvatarImages.value =
                            imageAccount?.let { owner ->
                                AvatarImageLoader(owner, it.avatars, AvatarImageCodec::thumbnail, viewModelScope)
                            }
                    }
                    history?.bindAccount(state)
                    turn?.bindAccount(state)
                    avatars?.bindAccount(state)
                    actions?.bindAccount(state)
                    val next = (state as? SessionState.SignedIn)?.revision
                    if (next != accountRevision) {
                        suggestions?.clear()
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
        suggestions?.clear()
        avatars?.clear()
        mutableAvatarImages.value?.close()
        mutableAvatarImages.value = null
        actions?.clear()
        history?.clear()
        turn?.clear()
        runSession { graph?.session?.logout() }
    }

    override fun onCleared() {
        suggestions?.close()
        avatars?.close()
        mutableAvatarImages.value?.close()
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
