package com.gmaicoson.socraticmind.chat.images

import com.gmaicoson.socraticmind.chat.ChatAvatarGateway
import com.gmaicoson.socraticmind.chat.ChatAvatarResource
import com.gmaicoson.socraticmind.chat.HistoryAccount
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit

data class DecodedAvatar<T : Any>(
    val image: T,
    val bytes: Int,
)

/** One instance per account revision and endpoint. UI cancellation does not cancel another cell's shared load. */
class AvatarImageLoader<T : Any>(
    val account: HistoryAccount,
    private val gateway: ChatAvatarGateway,
    private val decode: suspend (ByteArray) -> DecodedAvatar<T>,
    parentScope: CoroutineScope,
    private val maximumBytes: Int = 8 * 1024 * 1024,
    private val maximumEntries: Int = 32,
    private val maximumRequests: Int = 64,
) {
    private data class Request<T : Any>(
        val id: Long,
        val task: Deferred<DecodedAvatar<T>>,
    )

    private val lock = Any()
    private val scope = CoroutineScope(parentScope.coroutineContext + SupervisorJob(parentScope.coroutineContext[Job]))
    private val cache = LinkedHashMap<ChatAvatarResource, DecodedAvatar<T>>(16, 0.75f, true)
    private val requests = mutableMapOf<ChatAvatarResource, Request<T>>()
    private val workers = Semaphore(2)
    private val closedSignal = CompletableDeferred<Unit>()
    private var bytes = 0
    private var sequence = 0L
    private var closed = false

    init {
        require(maximumBytes > 0 && maximumEntries > 0 && maximumRequests > 0)
    }

    suspend fun load(resource: ChatAvatarResource): T {
        currentCoroutineContext().ensureActive()
        val task =
            synchronized(lock) {
                checkOpen()
                cache[resource]?.let { return it.image }
                requests[resource]?.task ?: create(resource)
            }
        val result =
            select {
                task.onAwait { it }
                closedSignal.onAwait { throw CancellationException("Avatar image scope was closed") }
            }
        currentCoroutineContext().ensureActive()
        return synchronized(lock) {
            checkOpen()
            result.image
        }
    }

    fun close() {
        val pending =
            synchronized(lock) {
                closed = true
                cache.clear()
                bytes = 0
                val pending = requests.values.map { it.task }
                requests.clear()
                pending
            }
        closedSignal.complete(Unit)
        pending.forEach { it.cancel() }
        scope.cancel()
    }

    private fun create(resource: ChatAvatarResource): Deferred<DecodedAvatar<T>> {
        check(requests.size < maximumRequests) { "Image request queue is full" }
        val id = ++sequence
        val task =
            scope.async(start = CoroutineStart.LAZY) {
                try {
                    val result =
                        workers.withPermit {
                            currentCoroutineContext().ensureActive()
                            val data = gateway.image(resource)
                            currentCoroutineContext().ensureActive()
                            require(data.isNotEmpty() && data.size <= ChatAvatarResource.MAXIMUM_IMAGE_BYTES)
                            decode(data).also { currentCoroutineContext().ensureActive() }
                        }
                    synchronized(lock) {
                        checkOpen()
                        require(result.bytes in 1..maximumBytes) { "Decoded image exceeds cache budget" }
                        cache[resource] = result
                        bytes += result.bytes
                        while (cache.size > maximumEntries || bytes > maximumBytes) {
                            val oldest = cache.entries.iterator()
                            bytes -= oldest.next().value.bytes
                            oldest.remove()
                        }
                    }
                    result
                } finally {
                    synchronized(lock) { if (requests[resource]?.id == id) requests.remove(resource) }
                }
            }
        requests[resource] = Request(id, task)
        task.start()
        return task
    }

    private fun checkOpen() {
        if (closed) throw CancellationException("Avatar image scope was closed")
    }
}
