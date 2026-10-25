package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.chat.AvatarImageFormat
import com.gmaicoson.socraticmind.chat.ChatAvatarGateway
import com.gmaicoson.socraticmind.chat.ChatAvatarResource
import com.gmaicoson.socraticmind.chat.ChatMode
import com.gmaicoson.socraticmind.chat.HistoryAccount
import com.gmaicoson.socraticmind.chat.images.AvatarImageLoader
import com.gmaicoson.socraticmind.chat.images.DecodedAvatar
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.IOException

class AvatarImageLoaderTest {
    @Test fun `duplicate cells share a request and one cancelled waiter leaves the other alive`(): Unit =
        runBlocking {
            withImages { loader, gateway ->
                val first = async { loader.load(resource(0)) }
                val second = async { loader.load(resource(0)) }
                val read = gateway.next()
                yield()
                first.cancel()
                assertTrue(
                    runCatching { withTimeout(1000) { first.await() } }.exceptionOrNull() is CancellationException,
                )
                assertFalse(second.isCompleted)
                read.complete(byteArrayOf(7))
                assertEquals(7, second.await())
                assertEquals(7, loader.load(resource(0)))
                assertEquals(1, gateway.count)
            }
        }

    @Test fun `at most two workers run and queued unique requests have a hard bound`(): Unit =
        runBlocking {
            withImages(maxRequests = 3) { loader, gateway ->
                val requests = (0..2).map { async { loader.load(resource(it)) } }
                val first = gateway.next()
                val second = gateway.next()
                yield()
                assertEquals(2, gateway.count)
                assertTrue(runCatching { loader.load(resource(3)) }.isFailure)
                first.complete(byteArrayOf(1))
                val third = gateway.next()
                second.complete(byteArrayOf(2))
                third.complete(byteArrayOf(3))
                requests.forEach { it.await() }
                assertEquals(3, gateway.count)
            }
        }

    @Test fun `cache evicts least recently used entries and respects decoded byte cost`(): Unit =
        runBlocking {
            for (maxBytes in listOf(12, 16)) {
                withImages(maxBytes = maxBytes, maxEntries = 2) { loader, gateway ->
                    suspend fun fetch(index: Int): Int {
                        val value = async { loader.load(resource(index)) }
                        gateway.next().complete(byteArrayOf(index.toByte()))
                        return value.await()
                    }
                    fetch(0)
                    fetch(1)
                    if (maxBytes == 16) {
                        assertEquals(0, loader.load(resource(0)))
                        fetch(2)
                        fetch(1)
                        assertEquals(4, gateway.count)
                    } else {
                        fetch(0)
                        assertEquals(3, gateway.count)
                    }
                }
            }
        }

    @Test fun `closing fences a decoder that ignores cancellation and a new scope starts empty`(): Unit =
        runBlocking {
            val entered = CompletableDeferred<Unit>()
            val gate = CompletableDeferred<Unit>()
            withImages(decode = {
                entered.complete(Unit)
                withContext(NonCancellable) { gate.await() }
                DecodedAvatar(7, 8)
            }) { loader, gateway ->
                try {
                    val old = async { runCatching { loader.load(resource(0)) } }
                    gateway.next().complete(byteArrayOf(7))
                    entered.await()
                    loader.close()
                    assertTrue(withTimeout(1000) { old.await() }.exceptionOrNull() is CancellationException)
                    withImages { newer, fresh ->
                        val value = async { newer.load(resource(0)) }
                        fresh.next().complete(byteArrayOf(8))
                        gate.complete(Unit)
                        assertEquals(8, value.await())
                        assertEquals(8, newer.load(resource(0)))
                    }
                    assertTrue(runCatching { loader.load(resource(0)) }.exceptionOrNull() is CancellationException)
                } finally {
                    gate.complete(Unit)
                }
            }
        }

    @Test fun `failed reads do not replay and a later explicit load may retry`(): Unit =
        runBlocking {
            withImages { loader, gateway ->
                val failed = async { runCatching { loader.load(resource(0)) } }
                gateway.next().completeExceptionally(IOException("synthetic"))
                assertTrue(failed.await().isFailure)
                assertEquals(1, gateway.count)
                val retry = async { loader.load(resource(0)) }
                gateway.next().complete(byteArrayOf(9))
                assertEquals(9, retry.await())
                assertEquals(2, gateway.count)
            }
        }

    @Test fun `encoded and decoded budgets are enforced before caching`(): Unit =
        runBlocking {
            var decodes = 0
            withImages(maxBytes = 8, decode = {
                decodes++
                DecodedAvatar(1, 9)
            }) { loader, gateway ->
                for (bytes in listOf(
                    byteArrayOf(),
                    ByteArray(ChatAvatarResource.MAXIMUM_IMAGE_BYTES + 1),
                    byteArrayOf(1),
                )) {
                    val request = async { runCatching { loader.load(resource(0)) } }
                    gateway.next().complete(bytes)
                    assertTrue(request.await().isFailure)
                }
                assertEquals(1, decodes)
                assertEquals(3, gateway.count)
            }
        }

    @Test fun `close releases active and queued callers without starting queued network work`(): Unit =
        runBlocking {
            withImages { loader, gateway ->
                val pending = (0..3).map { async { runCatching { loader.load(resource(it)) } } }
                gateway.next()
                gateway.next()
                yield()
                loader.close()
                pending.forEach { assertTrue(it.await().exceptionOrNull() is CancellationException) }
                assertEquals(2, gateway.count)
            }
        }
}

private fun resource(index: Int) = ChatAvatarResource(ChatAvatarResource.presets(ChatMode.NORMAL)[index])

private class ImageGateway : ChatAvatarGateway {
    private val reads = Channel<CompletableDeferred<ByteArray>>(Channel.UNLIMITED)
    private val pending = mutableListOf<CompletableDeferred<ByteArray>>()
    var count = 0
        private set

    override suspend fun image(resource: ChatAvatarResource): ByteArray {
        val read = CompletableDeferred<ByteArray>()
        count++
        pending.add(read)
        reads.send(read)
        return withContext(NonCancellable) { read.await() }
    }

    suspend fun next() = withTimeout(3000) { reads.receive() }

    fun close() {
        pending.forEach { it.completeExceptionally(CancellationException()) }
    }

    override suspend fun upload(
        token: String,
        ownerId: Long,
        sessionId: String,
        bytes: ByteArray,
        format: AvatarImageFormat,
    ): ChatAvatarResource = error("No upload in image presentation")

    override suspend fun delete(
        token: String,
        sessionId: String,
    ): Long = error("No delete in image presentation")
}

private suspend fun withImages(
    maxBytes: Int = 16,
    maxEntries: Int = 2,
    maxRequests: Int = 64,
    decode: suspend (ByteArray) -> DecodedAvatar<Int> = { DecodedAvatar(it.first().toInt(), 8) },
    body: suspend CoroutineScope.(AvatarImageLoader<Int>, ImageGateway) -> Unit,
) = coroutineScope {
    val gateway = ImageGateway()
    val loader = AvatarImageLoader(HistoryAccount(1, 1), gateway, decode, this, maxBytes, maxEntries, maxRequests)
    try {
        body(loader, gateway)
    } finally {
        loader.close()
        gateway.close()
    }
}
