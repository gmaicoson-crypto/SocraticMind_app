package com.gmaicoson.socraticmind.chat

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.yield
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.IOException

internal class ModelRead(
    val token: String,
) {
    val response = CompletableDeferred<ChatModelCatalog>()
    val completed = CompletableDeferred<Unit>()

    suspend fun result(): ChatModelCatalog =
        withContext(NonCancellable) {
            try {
                response.await()
            } finally {
                completed.complete(Unit)
            }
        }
}

internal class QueuedModelGateway : ChatModelGateway {
    private val calls = Channel<ModelRead>(Channel.UNLIMITED)
    private val pending = mutableListOf<ModelRead>()
    val count get() = pending.size

    override suspend fun catalog(token: String): ChatModelCatalog {
        val read = ModelRead(token)
        pending.add(read)
        calls.send(read)
        return read.result()
    }

    suspend fun next() = next(calls)

    fun close() {
        pending.forEach { it.response.completeExceptionally(CancellationException()) }
    }
}

internal class ModelHarness(
    scope: CoroutineScope,
) {
    val base = TurnHarness(scope)
    val gateway = QueuedModelGateway()
    val model = ChatModelController(base.session, gateway, base.model, scope)
    val account get() = checkNotNull(base.model.state.value.account)
    val catalog = ChatModelCatalog.decode(modelFixture().getValue("catalog"))

    suspend fun login(id: Long = 1) {
        if (base.session.state.value is com.gmaicoson.socraticmind.auth.SessionState.SignedIn) base.session.logout()
        base.login(id)
        base.ready()
        model.bindAccount(base.session.state.value)
    }

    suspend fun loaded() {
        gateway.next().response.complete(catalog)
        awaitHistory { !model.state.value.loading }
    }

    fun close() {
        model.close()
        gateway.close()
        base.close()
    }
}

class ChatModelControllerTest {
    @Test
    fun `default stays omitted and explicit choice is snapshotted for an active send`() =
        runBlocking {
            val h = ModelHarness(this)
            try {
                h.login()
                h.model.refresh()
                h.loaded()
                assertEquals(1, h.gateway.count)
                assertNull(h.model.state.value.selectedId)
                assertNull(h.base.model.state.value.model)
                val selected = h.catalog.models.last()
                h.model.select(selected.id, h.account)
                val stream = h.base.begin()
                assertEquals(selected.id, stream.request.model)
                h.model.select(null, h.account)
                assertEquals(selected.id, h.model.state.value.selectedId)
                h.model.refresh()
                h.gateway
                    .next()
                    .response
                    .complete(ChatModelCatalog(emptyList()))
                awaitHistory { !h.model.state.value.loading }
                assertFalse(h.base.model.state.value.modelAvailable)
                assertEquals(selected.id, stream.request.model)
                assertEquals(selected.id, stream.request.json().historyString("model"))
            } finally {
                h.close()
            }
        }

    @Test
    fun `removed selection blocks sends without fallback and explicit default recovers`() =
        runBlocking {
            val h = ModelHarness(this)
            try {
                h.login()
                h.loaded()
                val selected = h.catalog.models.last()
                h.model.select(selected.id, h.account)
                h.model.refresh()
                h.gateway
                    .next()
                    .response
                    .complete(ChatModelCatalog(h.catalog.models.dropLast(1)))
                awaitHistory { !h.model.state.value.loading }
                assertEquals(selected, h.model.state.value.selected)
                assertFalse(h.model.state.value.available)
                assertFalse(h.base.model.state.value.canSend)
                h.base.model.send("标准")
                yield()
                assertTrue(
                    h.base.gateway.streams
                        .tryReceive()
                        .isFailure,
                )
                h.model.select("unknown-id", h.account)
                assertEquals(selected, h.model.state.value.selected)
                h.model.select(null, h.account)
                assertTrue(h.base.model.state.value.canSend)
                assertNull(
                    h.base
                        .begin()
                        .request.model,
                )
            } finally {
                h.close()
            }
        }

    @Test
    fun `failed refresh keeps the previous selection and a later successful refresh updates its label`() =
        runBlocking {
            val h = ModelHarness(this)
            try {
                h.login()
                h.loaded()
                val selected = h.catalog.models.last()
                h.model.select(selected.id, h.account)
                h.model.refresh()
                h.gateway
                    .next()
                    .response
                    .completeExceptionally(IOException("offline"))
                awaitHistory { !h.model.state.value.loading }
                assertEquals(selected, h.model.state.value.selected)
                assertTrue(h.model.state.value.available)
                assertTrue(h.model.state.value.notice != null)
                h.model.refresh()
                h.gateway
                    .next()
                    .response
                    .complete(ChatModelCatalog(listOf(selected.copy(name = "新名称"))))
                awaitHistory { !h.model.state.value.loading }
                assertEquals("新名称", h.model.state.value.label)
                assertEquals(selected.id, h.base.model.state.value.model)
                assertNull(h.model.state.value.notice)
            } finally {
                h.close()
            }
        }

    @Test
    fun `late directory and stale selection cannot cross account or same-user revision`() =
        runBlocking {
            val h = ModelHarness(this)
            try {
                h.login()
                val oldAccount = h.account
                val old = h.gateway.next()
                h.login(2)
                h.gateway
                    .next()
                    .response
                    .complete(ChatModelCatalog(emptyList()))
                awaitHistory { !h.model.state.value.loading }
                old.response.complete(h.catalog)
                old.completed.await()
                yield()
                assertTrue(
                    h.model.state.value.catalog
                        ?.models
                        ?.isEmpty() == true,
                )
                h.model.select(
                    h.catalog.models
                        .last()
                        .id,
                    oldAccount,
                )
                assertNull(h.model.state.value.selectedId)
                h.login(1)
                h.loaded()
                h.model.select(
                    h.catalog.models
                        .last()
                        .id,
                    h.account,
                )
                h.login(1)
                assertNull(h.model.state.value.selectedId)
                assertNull(h.base.model.state.value.model)
                h.loaded()
            } finally {
                h.close()
            }
        }

    @Test
    fun `initial failure permits explicit server default and logout clears cached choices`() =
        runBlocking {
            val h = ModelHarness(this)
            try {
                h.login()
                h.gateway
                    .next()
                    .response
                    .completeExceptionally(IOException("offline"))
                awaitHistory { !h.model.state.value.loading }
                assertTrue(h.base.model.state.value.canSend)
                assertEquals("服务端默认", h.model.state.value.label)
                assertTrue(h.model.state.value.notice != null)
                h.model.refresh()
                h.loaded()
                h.model.select(
                    h.catalog.models
                        .last()
                        .id,
                    h.account,
                )
                h.base.session.logout()
                h.base.model.bindAccount(h.base.session.state.value)
                h.model.bindAccount(h.base.session.state.value)
                assertNull(h.model.state.value.account)
                assertNull(h.model.state.value.catalog)
                assertNull(h.base.model.state.value.model)
            } finally {
                h.close()
            }
        }

    @Test
    fun `canonically equivalent IDs stay distinct through selection and disappearance`() =
        runBlocking {
            val h = ModelHarness(this)
            try {
                h.login()
                val first =
                    h.catalog.models
                        .first()
                        .copy(id = "é")
                val second = first.copy(id = "e\u0301")
                val input = mutableListOf(first, second)
                val snapshot = ChatModelCatalog(input)
                input.clear()
                h.gateway
                    .next()
                    .response
                    .complete(snapshot)
                awaitHistory { !h.model.state.value.loading }
                h.model.select(second.id, h.account)
                assertEquals(second.id, h.base.model.state.value.model)
                h.model.refresh()
                h.gateway
                    .next()
                    .response
                    .complete(ChatModelCatalog(listOf(first)))
                awaitHistory { !h.model.state.value.loading }
                assertFalse(h.model.state.value.available)
            } finally {
                h.close()
            }
        }
}
