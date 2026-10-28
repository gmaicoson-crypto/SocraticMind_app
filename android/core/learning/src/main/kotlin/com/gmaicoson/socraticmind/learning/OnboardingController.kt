package com.gmaicoson.socraticmind.learning

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

/** Owns the pending transaction. Local cancellation never asserts server cancellation. */
class OnboardingController(
    private val session: SessionStore,
    private val gateway: OnboardingGateway,
    private val journal: OnboardingJournal,
    parentScope: CoroutineScope,
    private val newId: () -> OnboardingID = { OnboardingID.create() },
    private val pollDelays: List<Long> = listOf(500, 1000, 2000),
) {
    private val lock = Any()
    private val scope = CoroutineScope(parentScope.coroutineContext + SupervisorJob(parentScope.coroutineContext[Job]))
    private val mutableState = MutableStateFlow(OnboardingState())
    val state = mutableState.asStateFlow()
    private var job: Job? = null
    private var ticket = 0L
    private var closed = false

    fun bindAccount(value: SessionState): Unit =
        synchronized(lock) {
            val account = OnboardingAccount.from(value)
            if (closed || account != OnboardingAccount.from(session.state.value) ||
                account == state.value.account
            ) {
                return
            }
            clearLocked()
            if (account == null) return
            mutableState.value = OnboardingState(account = account)
            launch { restore(it) }
        }

    fun close() {
        synchronized(lock) {
            closed = true
            clearLocked()
        }
        scope.cancel()
    }

    fun acknowledge(receipt: OnboardingResult) =
        synchronized(lock) {
            if (current() && state.value.receipt == receipt) mutableState.value = state.value.copy(receipt = null)
        }

    fun start(
        form: OnboardingForm,
        model: String? = null,
    ): Unit =
        synchronized(lock) {
            if (!current() || !state.value.canStart) return
            model?.let { requireText(it, 100) }
            val pending = PendingOnboarding(checkNotNull(state.value.account).ownerId, newId(), newId())
            mutableState.value = state.value.copy(pending = pending, run = null)
            launch { operation ->
                storage { journal.save(pending) }
                val run = request(operation) { gateway.start(it, pending.runId, form, model) }
                settle(operation, pending, run)
            }
        }

    fun refresh(): Unit =
        synchronized(lock) {
            if (!current() || state.value.busy) return
            val pending = state.value.pending
            val terminal =
                state.value.run?.takeIf {
                    it.status in listOf(OnboardingStatus.COMPLETED, OnboardingStatus.CANCELLED)
                }
            if (pending != null && terminal != null) {
                // A remove may succeed before its verification throws. Keep the known
                // receipt and retry idempotent cleanup instead of discarding it on an empty read.
                launch { settle(it, pending, terminal) }
            } else {
                launch { restore(it) }
            }
        }

    fun answer(text: String): Unit =
        synchronized(lock) {
            if (!current() || !state.value.canAnswer) return
            requireText(text, 5000)
            val run = checkNotNull(state.value.run)
            mutate { gateway.answer(it, run.id, run.version, checkNotNull(run.step).id, text) }
        }

    fun revise(
        goal: String,
        minutes: Int,
        targetDate: String?,
        timezone: String,
    ): Unit =
        synchronized(lock) {
            if (!current() || !state.value.canRevise) return
            requireText(goal, 300)
            requireText(timezone, 100)
            require(minutes in 5..240)
            targetDate?.let(::requireDate)
            val run = checkNotNull(state.value.run)
            mutate { gateway.revise(it, run.id, run.version, goal, minutes, targetDate, timezone) }
        }

    fun confirm(): Unit =
        synchronized(lock) {
            if (!current() || !state.value.canConfirm) return
            val run = checkNotNull(state.value.run)
            val pending = checkNotNull(state.value.pending)
            mutate { gateway.confirm(it, run.id, run.version, pending.confirmationId.value) }
        }

    fun retry(): Unit =
        synchronized(lock) {
            if (!current() || !state.value.canRetry) return
            val run = checkNotNull(state.value.run)
            mutate { gateway.retry(it, run.id, run.version) }
        }

    fun cancel(): Unit =
        synchronized(lock) {
            if (!current() || !state.value.canCancel) return
            val pending = checkNotNull(state.value.pending)
            launch { operation ->
                // A cancelled initial save may still finish its atomic IO. Serialize with it,
                // verify the same record, then cancel even if creation has not arrived yet.
                storage { journal.save(pending) }
                settle(operation, pending, request(operation) { gateway.cancel(it, pending.runId) })
            }
        }

    private fun mutate(block: suspend (String) -> OnboardingRun) {
        val pending = checkNotNull(state.value.pending)
        launch { operation -> settle(operation, pending, request(operation, block)) }
    }

    private suspend fun restore(operation: Operation) {
        val pending = storage { journal.read(operation.account.ownerId) }
        update(operation) { it.copy(ready = true, pending = pending, run = null, needsRefresh = pending != null) }
        if (pending != null) settle(operation, pending, request(operation) { gateway.read(it, pending.runId) })
    }

    private suspend fun settle(
        operation: Operation,
        pending: PendingOnboarding,
        initial: OnboardingRun,
    ) {
        var run = initial
        var polls = 0
        while (true) {
            require(run.id == pending.runId)
            update(operation) { it.copy(run = run, needsRefresh = false, issue = null) }
            if (run.status in listOf(OnboardingStatus.COMPLETED, OnboardingStatus.CANCELLED)) {
                val result = if (run.status == OnboardingStatus.COMPLETED) checkNotNull(run.result) else null
                requireCurrent(operation)
                storage { journal.clear(pending) }
                update(operation) { it.copy(pending = null, receipt = result) }
                return
            }
            if (!run.processing || polls >= pollDelays.size) return
            delay(pollDelays[polls++])
            run = request(operation) { gateway.read(it, pending.runId) }
        }
    }

    private suspend fun request(
        operation: Operation,
        block: suspend (String) -> OnboardingRun,
    ): OnboardingRun =
        session.authenticated { token ->
            requireCurrent(operation)
            block(token)
        }

    private fun launch(block: suspend (Operation) -> Unit) {
        job?.cancel()
        val operation = Operation(++ticket, checkNotNull(state.value.account))
        mutableState.value = state.value.copy(busy = true, issue = null)
        job =
            scope.launch(start = CoroutineStart.LAZY) {
                try {
                    block(operation)
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    synchronized(lock) {
                        if (valid(operation)) {
                            val issue =
                                when {
                                    error is StorageFailure -> OnboardingIssue.STORAGE
                                    error is HttpFailure && error.status == 404 -> OnboardingIssue.NOT_FOUND
                                    error is HttpFailure && error.status == 409 -> OnboardingIssue.CONFLICT
                                    else -> OnboardingIssue.REQUEST
                                }
                            mutableState.value = state.value.copy(issue = issue, needsRefresh = true)
                        }
                    }
                } finally {
                    synchronized(lock) {
                        if (valid(operation)) mutableState.value = state.value.copy(busy = false)
                    }
                }
            }
        job?.start()
    }

    private fun update(
        operation: Operation,
        transform: (OnboardingState) -> OnboardingState,
    ) = synchronized(lock) {
        requireCurrent(operation)
        mutableState.value = transform(state.value)
    }

    private fun current() =
        !closed && state.value.account != null && state.value.account == OnboardingAccount.from(session.state.value)

    private fun valid(operation: Operation) =
        current() && operation.ticket == ticket && operation.account == state.value.account

    private fun requireCurrent(operation: Operation) =
        synchronized(lock) {
            if (!valid(operation)) throw CancellationException()
        }

    private fun clearLocked() {
        ticket++
        job?.cancel()
        job = null
        mutableState.value = OnboardingState()
    }

    private data class Operation(
        val ticket: Long,
        val account: OnboardingAccount,
    )

    private class StorageFailure : IllegalStateException()

    private suspend fun <T> storage(block: suspend () -> T): T =
        try {
            block()
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            throw StorageFailure()
        }
}
