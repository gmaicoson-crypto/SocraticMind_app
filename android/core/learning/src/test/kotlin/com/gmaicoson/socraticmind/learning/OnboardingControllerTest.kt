package com.gmaicoson.socraticmind.learning

import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class OnboardingControllerTest {
    @Test
    fun `persist before start and carry observed versions through confirm with one receipt`() =
        runBlocking {
            val h = LearningHarness(this)
            try {
                h.login()
                h.ready()
                h.model.start(learningForm())
                val start = h.gateway.next()
                assertNotNull(start.saved)
                assertEquals(start.id, start.saved!!.runId)
                h.model.start(learningForm())
                assertEquals(1, h.gateway.observed.size)
                h.finish(start, "diagnosing")
                assertTrue(h.model.state.value.canAnswer)
                h.model.answer("答案")
                val answer = h.gateway.next()
                assertEquals(
                    h.model.state.value.run!!
                        .version,
                    answer.version,
                )
                h.finish(answer, "preview")
                h.model.revise("调整", 20, null, "Asia/Shanghai")
                val revise = h.gateway.next()
                assertEquals(
                    h.model.state.value.run!!
                        .version,
                    revise.version,
                )
                h.finish(revise, "edited")
                h.model.confirm()
                h.model.confirm()
                val confirm = h.gateway.next()
                assertEquals(start.saved!!.confirmationId.value, confirm.confirmation)
                assertEquals(
                    h.model.state.value.run!!
                        .version,
                    confirm.version,
                )
                h.finish(confirm, "completed")
                val receipt = h.model.state.value.receipt!!
                assertNull(h.journal.read(1))
                assertFalse(h.model.state.value.canStart)
                assertEquals(1, h.gateway.observed.count { it.kind == "confirm" })
                h.model.acknowledge(receipt)
                assertTrue(h.model.state.value.canStart)
            } finally {
                h.close()
            }
        }

    @Test
    fun `unknown create and 404 retain identity until explicit safe cancellation`() =
        runBlocking {
            val h = LearningHarness(this)
            try {
                h.login()
                h.ready()
                h.model.start(learningForm())
                val start = h.gateway.next()
                start.response.completeExceptionally(HttpFailure(503, null, "synthetic", true))
                awaitLearning { !h.model.state.value.busy }
                h.model.start(learningForm())
                h.model.confirm()
                assertEquals(1, h.gateway.observed.size)
                h.model.refresh()
                val read = h.gateway.next()
                assertEquals(start.id, read.id)
                read.response.completeExceptionally(HttpFailure(404, null, "synthetic", false))
                awaitLearning { h.model.state.value.issue == OnboardingIssue.NOT_FOUND }
                assertNotNull(h.journal.read(1))
                assertFalse(h.model.state.value.canStart)
                h.model.cancel()
                val cancel = h.gateway.next()
                assertEquals("cancel", cancel.kind)
                assertEquals(start.id, cancel.id)
                h.finish(cancel, "cancelled")
                assertNull(h.journal.read(1))
                assertTrue(h.model.state.value.canStart)
            } finally {
                h.close()
            }
        }

    @Test
    fun `cancel interrupts local request but ignores its late success`() =
        runBlocking {
            val h = LearningHarness(this)
            try {
                h.login()
                h.ready()
                h.model.start(learningForm())
                val start = h.gateway.next()
                h.model.cancel()
                val cancel = h.gateway.next()
                h.finish(cancel, "cancelled")
                start.response.complete(learningRun("completed", start.id))
                h.model.refresh()
                awaitLearning { !h.model.state.value.busy }
                assertNull(h.model.state.value.receipt)
                assertTrue(h.model.state.value.canStart)
            } finally {
                h.close()
            }
        }

    @Test
    fun `account switch fences late 401 and restores only original owner identifiers`() =
        runBlocking {
            val h = LearningHarness(this)
            try {
                h.login()
                h.ready()
                h.model.start(learningForm())
                val old = h.gateway.next()
                val prior = h.session.state.value
                h.login(2)
                h.ready()
                h.model.bindAccount(prior)
                old.response.completeExceptionally(HttpFailure(401, null, "late", false))
                assertEquals(
                    2L,
                    h.model.state.value.account!!
                        .ownerId,
                )
                assertTrue(h.session.state.value is SessionState.SignedIn)
                h.login(1)
                val restore = h.gateway.next()
                assertEquals(old.id, restore.id)
                assertEquals("read", restore.kind)
                h.finish(restore, "preview")
                h.model.confirm()
                val confirm = h.gateway.next()
                assertEquals(old.saved!!.confirmationId.value, confirm.confirmation)
                h.finish(confirm, "completed")
            } finally {
                h.close()
            }
        }

    @Test
    fun `failed save never posts and failed terminal clear keeps recovery for retry`() =
        runBlocking {
            val h = LearningHarness(this)
            try {
                h.login()
                h.ready()
                h.journal.failSave = true
                h.model.start(learningForm())
                awaitLearning { h.model.state.value.issue == OnboardingIssue.STORAGE }
                assertTrue(h.gateway.observed.isEmpty())
                assertFalse(h.model.state.value.canStart)
                h.journal.failSave = false
                h.model.refresh()
                val read = h.gateway.next()
                h.journal.failClear = true
                h.finish(read, "completed")
                assertNotNull(h.model.state.value.pending)
                assertNull(h.model.state.value.receipt)
                assertEquals(OnboardingIssue.STORAGE, h.model.state.value.issue)
                h.journal.failClear = false
                h.model.refresh()
                awaitLearning { !h.model.state.value.busy }
                assertNotNull(h.model.state.value.receipt)
                assertNull(h.journal.read(1))
            } finally {
                h.close()
            }
        }

    @Test
    fun `processing polls are bounded and version conflict requires read before mutation`() =
        runBlocking {
            val h = LearningHarness(this, polls = listOf(1, 1))
            try {
                h.login()
                h.ready()
                h.model.start(learningForm())
                repeat(3) {
                    val call = h.gateway.next()
                    call.response.complete(learningRun("processing", call.id))
                }
                awaitLearning { !h.model.state.value.busy }
                assertEquals(3, h.gateway.observed.size)
                assertFalse(h.model.state.value.canConfirm)
                h.model.refresh()
                h.finish(h.gateway.next(), "preview")
                h.model.confirm()
                val confirm = h.gateway.next()
                confirm.response.completeExceptionally(HttpFailure(409, "AGENT_STATE_CONFLICT", "synthetic", false))
                awaitLearning { !h.model.state.value.busy }
                h.model.confirm()
                h.model.retry()
                assertEquals(1, h.gateway.observed.count { it.kind == "confirm" })
                assertTrue(h.model.state.value.needsRefresh)
                h.model.refresh()
                h.finish(h.gateway.next(), "failed")
                assertTrue(h.model.state.value.canRetry)
                h.model.retry()
                val retry = h.gateway.next()
                assertEquals(
                    h.model.state.value.run!!
                        .version,
                    retry.version,
                )
                h.finish(retry, "diagnosing")
            } finally {
                h.close()
            }
        }

    @Test
    fun `read failure blocks new work and post-delete error preserves known completion`() =
        runBlocking {
            val h = LearningHarness(this)
            try {
                h.journal.failRead = true
                h.login()
                awaitLearning { h.model.state.value.issue == OnboardingIssue.STORAGE }
                h.model.start(learningForm())
                assertTrue(h.gateway.observed.isEmpty())
                h.journal.failRead = false
                h.model.refresh()
                h.ready()
                h.model.start(learningForm())
                val start = h.gateway.next()
                h.finish(start, "preview")
                h.journal.failAfterClear = true
                h.model.confirm()
                h.finish(h.gateway.next(), "completed")
                assertNull(h.journal.read(1))
                assertNotNull(h.model.state.value.pending)
                assertEquals(OnboardingIssue.STORAGE, h.model.state.value.issue)
                val requests = h.gateway.observed.size
                h.journal.failAfterClear = false
                h.model.refresh()
                awaitLearning { !h.model.state.value.busy }
                assertNotNull(h.model.state.value.receipt)
                assertNull(h.model.state.value.pending)
                assertEquals(requests, h.gateway.observed.size)
            } finally {
                h.close()
            }
        }

    @Test
    fun `failed reread and wrong response identity never permit starting over`() =
        runBlocking {
            val h = LearningHarness(this)
            try {
                h.login()
                h.ready()
                h.journal.failRead = true
                h.model.refresh()
                awaitLearning { !h.model.state.value.busy }
                assertFalse(h.model.state.value.canStart)
                h.model.start(learningForm())
                assertTrue(h.gateway.observed.isEmpty())
                h.journal.failRead = false
                h.model.refresh()
                h.ready()
                h.model.start(learningForm())
                val start = h.gateway.next()
                start.response.complete(learningRun("completed", OnboardingID.create()))
                awaitLearning { !h.model.state.value.busy }
                assertEquals(OnboardingIssue.REQUEST, h.model.state.value.issue)
                assertNull(h.model.state.value.receipt)
                assertEquals(
                    start.id,
                    h.model.state.value.pending!!
                        .runId,
                )
                h.model.refresh()
                val read = h.gateway.next()
                assertEquals(start.id, read.id)
                h.finish(read, "preview")
                assertTrue(h.model.state.value.canConfirm)
            } finally {
                h.close()
            }
        }
}
