package com.gmaicoson.socraticmind.auth

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.ceil

/** One reusable form owner. Network work runs outside the short state critical section. */
class AuthFormController(
    private val session: SessionStore,
    private val recovery: AccountRecoveryGateway,
    private val nowMillis: () -> Long = { System.nanoTime() / 1_000_000 },
) {
    private val lock = Any()
    private val mutableState = MutableStateFlow(AuthFormState())
    val state = mutableState.asStateFlow()
    private var generation = 0L
    private val deadlines = mutableMapOf<String, Long>()

    fun edit(
        field: AuthField,
        value: String,
    ) = synchronized(lock) {
        val current = mutableState.value
        if (current.busy != null) return@synchronized
        val edited =
            when (field) {
                AuthField.USERNAME -> current.copy(username = value)
                AuthField.EMAIL -> current.copy(email = value, code = "")
                AuthField.PASSWORD -> current.copy(password = value)
                AuthField.CONFIRMATION -> current.copy(confirmation = value)
                AuthField.CODE -> current.copy(code = value)
            }
        mutableState.value = edited.copy(error = null, notice = null, cooldownSeconds = remaining(edited.email))
    }

    fun switchMode(mode: AuthMode) =
        synchronized(lock) {
            val current = mutableState.value
            if (current.busy != null || mode == current.mode) return@synchronized
            generation++
            mutableState.value =
                current.copy(
                    mode = mode,
                    password = "",
                    confirmation = "",
                    code = "",
                    error = null,
                    notice = null,
                    cooldownSeconds = remaining(current.email),
                )
        }

    fun refreshClock() =
        synchronized(lock) {
            mutableState.value = mutableState.value.let { it.copy(cooldownSeconds = remaining(it.email)) }
        }

    fun reset() =
        synchronized(lock) {
            generation++
            deadlines.clear()
            mutableState.value = AuthFormState()
        }

    suspend fun submit() {
        val (ticket, input) = begin(AuthOperation.SUBMIT) ?: return
        try {
            val notice =
                when (input.mode) {
                    AuthMode.LOGIN -> {
                        session.login(input.email, input.password)
                        null
                    }

                    AuthMode.REGISTER -> {
                        session.register(input.username, input.email, input.password, input.code)
                        null
                    }

                    AuthMode.RESET -> {
                        recovery.resetPassword(input.email, input.code, input.password)
                        "密码已更新，请使用新密码登录。"
                    }
                }
            currentCoroutineContext().ensureActive()
            finish(ticket) {
                it.copy(mode = AuthMode.LOGIN, password = "", confirmation = "", code = "", notice = notice)
            }
        } catch (error: Exception) {
            failed(ticket, error)
            if (error is CancellationException) throw error
        }
    }

    suspend fun sendCode() {
        val (ticket, input) = begin(AuthOperation.SEND_CODE) ?: return
        try {
            val purpose = if (input.mode == AuthMode.REGISTER) CodePurpose.REGISTER else CodePurpose.RESET
            val message = recovery.sendCode(input.email, purpose)
            currentCoroutineContext().ensureActive()
            finish(ticket) { it.copy(notice = message) }
        } catch (error: Exception) {
            failed(ticket, error)
            if (error is CancellationException) throw error
        }
    }

    private fun begin(operation: AuthOperation): Pair<Long, AuthFormState>? =
        synchronized(lock) {
            val current = mutableState.value
            if (current.busy != null || session.state.value !is SessionState.SignedOut) return@synchronized null
            if (operation == AuthOperation.SEND_CODE && current.mode == AuthMode.LOGIN) return@synchronized null
            val error = current.validation(codeOnly = operation == AuthOperation.SEND_CODE)
            if (error != null) {
                mutableState.value = current.copy(error = error, notice = null)
                return@synchronized null
            }
            if (operation == AuthOperation.SEND_CODE) {
                val wait = remaining(current.email)
                if (wait > 0) {
                    mutableState.value = current.copy(cooldownSeconds = wait)
                    return@synchronized null
                }
                val now = nowMillis()
                deadlines.entries.removeAll { it.value <= now }
                // The server consumes the email limit before sending; even a timeout can consume it.
                deadlines[normalizedFormEmail(current.email)] = now + 60_000
            }
            generation++
            mutableState.value =
                current.copy(busy = operation, error = null, notice = null, cooldownSeconds = remaining(current.email))
            generation to current
        }

    private fun remaining(email: String): Int {
        val deadline = deadlines[normalizedFormEmail(email)] ?: return 0
        return ceil((deadline - nowMillis()).coerceAtLeast(0) / 1000.0).toInt()
    }

    private fun finish(
        ticket: Long,
        update: (AuthFormState) -> AuthFormState,
    ) = synchronized(lock) {
        if (ticket != generation) return@synchronized
        val current = update(mutableState.value)
        mutableState.value = current.copy(busy = null, cooldownSeconds = remaining(current.email))
    }

    private fun failed(
        ticket: Long,
        error: Exception,
    ) = finish(ticket) {
        it.copy(error = if (error is CancellationException) null else accountErrorMessage(error), notice = null)
    }
}
