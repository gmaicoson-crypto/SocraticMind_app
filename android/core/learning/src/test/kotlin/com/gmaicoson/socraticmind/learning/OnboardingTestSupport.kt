package com.gmaicoson.socraticmind.learning

import com.gmaicoson.socraticmind.auth.AuthGrant
import com.gmaicoson.socraticmind.auth.AuthUser
import com.gmaicoson.socraticmind.auth.SessionGateway
import com.gmaicoson.socraticmind.auth.SessionStore
import com.gmaicoson.socraticmind.auth.TokenVault
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.atomic.AtomicReference

internal fun learningFixture(name: String) =
    Json.parseToJsonElement(Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve(name))).obj()

internal fun learningForm() = decodeForm(learningFixture("onboarding-runs.json").getValue("request"))

internal fun learningRun(
    name: String,
    id: OnboardingID,
): OnboardingRun {
    val data = learningFixture("onboarding-runs.json").getValue("responses").obj().getValue(name)
    val original = OnboardingID(data.obj().text("run_id", 36))
    return OnboardingRun.decode(data, original).copy(id = id)
}

internal suspend fun awaitLearning(check: () -> Boolean) = withTimeout(4000) { while (!check()) delay(1) }

internal class MemoryOnboardingJournal : OnboardingJournal {
    val records = mutableMapOf<Long, PendingOnboarding>()
    var failSave = false
    var failRead = false
    var failClear = false
    var failAfterClear = false

    override suspend fun read(ownerId: Long): PendingOnboarding? {
        if (failRead) throw IOException()
        return records[ownerId]
    }

    override suspend fun save(pending: PendingOnboarding) {
        check(records[pending.ownerId] == null || records[pending.ownerId] == pending)
        records[pending.ownerId] = pending
        if (failSave) throw IOException()
    }

    override suspend fun clear(pending: PendingOnboarding) {
        if (failClear) throw IOException()
        check(records[pending.ownerId] == null || records[pending.ownerId] == pending)
        records.remove(pending.ownerId)
        if (failAfterClear) throw IOException()
    }
}

internal data class LearningCall(
    val kind: String,
    val token: String,
    val id: OnboardingID,
    val version: Int? = null,
    val confirmation: String? = null,
    val saved: PendingOnboarding? = null,
) {
    val response = CompletableDeferred<OnboardingRun>()
}

internal class QueuedLearningGateway(
    private val journal: MemoryOnboardingJournal,
) : OnboardingGateway {
    val calls = Channel<LearningCall>(Channel.UNLIMITED)
    val observed = mutableListOf<LearningCall>()

    private suspend fun call(
        kind: String,
        token: String,
        id: OnboardingID,
        version: Int? = null,
        confirmation: String? = null,
    ): OnboardingRun {
        val call =
            LearningCall(
                kind,
                token,
                id,
                version,
                confirmation,
                journal.records.values.singleOrNull {
                    it.runId ==
                        id
                },
            )
        observed.add(call)
        calls.send(call)
        return withContext(NonCancellable) { call.response.await() }
    }

    suspend fun next() = withTimeout(4000) { calls.receive() }

    override suspend fun start(
        token: String,
        id: OnboardingID,
        form: OnboardingForm,
        model: String?,
    ) = call("start", token, id)

    override suspend fun read(
        token: String,
        id: OnboardingID,
    ) = call("read", token, id)

    override suspend fun answer(
        token: String,
        id: OnboardingID,
        version: Int,
        stepId: String,
        answer: String,
    ) = call("answer", token, id, version)

    override suspend fun revise(
        token: String,
        id: OnboardingID,
        version: Int,
        goal: String,
        dailyMinutes: Int,
        targetDate: String?,
        timezone: String,
    ) = call("revise", token, id, version)

    override suspend fun confirm(
        token: String,
        id: OnboardingID,
        version: Int,
        requestId: String,
    ) = call("confirm", token, id, version, requestId)

    override suspend fun cancel(
        token: String,
        id: OnboardingID,
    ) = call("cancel", token, id)

    override suspend fun retry(
        token: String,
        id: OnboardingID,
        version: Int,
    ) = call("retry", token, id, version)

    fun close() {
        observed.forEach { it.response.completeExceptionally(IOException("cleanup")) }
    }
}

internal class LearningHarness(
    scope: CoroutineScope,
    val journal: MemoryOnboardingJournal = MemoryOnboardingJournal(),
    polls: List<Long> = emptyList(),
) {
    private var owner = 1L
    private val token = AtomicReference<String?>()
    private val auth =
        object : SessionGateway {
            private fun user() = AuthUser(owner, "User", "u@example.test", "", "", "", 30, "标准")

            override suspend fun login(
                email: String,
                password: String,
            ) = AuthGrant("synthetic-$owner", user())

            override suspend fun register(
                username: String,
                email: String,
                password: String,
                code: String,
            ) = login(email, password)

            override suspend fun profile(token: String) = user()
        }
    val session =
        SessionStore(
            auth,
            object : TokenVault {
                override fun read() = token.get()

                override fun write(token: String) {
                    this@LearningHarness.token.set(token)
                }

                override fun clear() {
                    token.set(null)
                }
            },
        )
    val gateway = QueuedLearningGateway(journal)
    val model = OnboardingController(session, gateway, journal, scope, pollDelays = polls)

    suspend fun login(id: Long = 1) {
        session.logout()
        owner = id
        session.login("u@example.test", "synthetic")
        model.bindAccount(session.state.value)
    }

    suspend fun ready() = awaitLearning { model.state.value.canStart }

    suspend fun finish(
        call: LearningCall,
        state: String,
    ) {
        call.response.complete(learningRun(state, call.id))
        awaitLearning { !model.state.value.busy }
    }

    fun close() {
        model.close()
        gateway.close()
    }
}
