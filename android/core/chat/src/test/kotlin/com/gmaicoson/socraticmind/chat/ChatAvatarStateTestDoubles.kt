package com.gmaicoson.socraticmind.chat

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withContext
import java.io.IOException
import java.security.MessageDigest

internal class AvatarWrite(
    val kind: String,
    val ownerId: Long?,
    val sessionId: String,
    val bytes: ByteArray = byteArrayOf(),
) {
    val response = CompletableDeferred<ChatAvatarResource?>()
    val completed = CompletableDeferred<Unit>()

    suspend fun result(): ChatAvatarResource? =
        withContext(NonCancellable) {
            try {
                response.await()
            } finally {
                completed.complete(Unit)
            }
        }
}

internal class QueuedAvatarGateway : ChatAvatarGateway {
    val calls = Channel<AvatarWrite>(Channel.UNLIMITED)
    private val pending = mutableListOf<AvatarWrite>()
    var count = 0
        private set

    override suspend fun upload(
        token: String,
        ownerId: Long,
        sessionId: String,
        bytes: ByteArray,
        format: AvatarImageFormat,
    ): ChatAvatarResource = checkNotNull(write(AvatarWrite("upload", ownerId, sessionId, bytes)).result())

    override suspend fun delete(
        token: String,
        sessionId: String,
    ): Long {
        write(AvatarWrite("delete", null, sessionId)).result()
        return 1
    }

    override suspend fun image(resource: ChatAvatarResource): ByteArray = error("State does not decode images")

    private suspend fun write(value: AvatarWrite): AvatarWrite {
        count++
        pending.add(value)
        calls.send(value)
        return value
    }

    fun close() {
        pending.forEach { it.response.completeExceptionally(CancellationException("cleanup")) }
    }
}

internal class MemoryAvatarStore : ChatAvatarStore {
    val values = mutableMapOf<Long, Map<String, ChatAvatarResource>>()
    var readFailure = false
    var writeFailure = false
    var failAfterWrite = false
    var writes = 0
    var readGate: CompletableDeferred<Unit>? = null
    private val readGates = mutableListOf<CompletableDeferred<Unit>>()
    var completedReads = 0
        private set
    val reads = Channel<Long>(Channel.UNLIMITED)

    override suspend fun read(ownerId: Long): Map<String, ChatAvatarResource> {
        val result = values[ownerId].orEmpty().toMap()
        reads.send(ownerId)
        try {
            readGate?.let {
                readGates.add(it)
                withContext(NonCancellable) { it.await() }
            }
            if (readFailure) throw IOException("synthetic read")
            return result
        } finally {
            completedReads++
        }
    }

    fun releaseReads() {
        readGates.forEach { it.complete(Unit) }
    }

    override suspend fun replace(
        ownerId: Long,
        sessionId: String,
        expected: ChatAvatarResource?,
        value: ChatAvatarResource?,
    ) {
        writes++
        if (writeFailure) throw IOException("synthetic write")
        val old = values[ownerId].orEmpty()
        if (old[sessionId] != expected) throw ChatAvatarException(ChatAvatarFailure.CONFLICT)
        values[ownerId] = if (value == null) old - sessionId else old + (sessionId to value)
        if (failAfterWrite) throw IOException("synthetic readback")
    }

    override suspend fun clear(ownerId: Long) {
        values.remove(ownerId)
    }
}

internal class AvatarHarness(
    scope: CoroutineScope,
) {
    val base: ActionsHarness
    val store = MemoryAvatarStore()
    val gateway = QueuedAvatarGateway()
    val model: ChatAvatarController

    init {
        var avatar: ChatAvatarController? = null
        base = ActionsHarness(scope) { account, id -> avatar?.forgetDeletedSession(account, id) }
        model = ChatAvatarController(base.session, gateway, store, base.history.model, base.turn, scope)
        avatar = model
    }

    suspend fun login(id: Long = 1) {
        model.clear()
        base.login(id)
        model.bindAccount(base.session.state.value)
        awaitHistory { !model.state.value.loading }
    }

    fun picker(): ChatAvatarPicker {
        model.open(checkNotNull(base.history.model.state.value.selected).target)
        return checkNotNull(model.state.value.picker)
    }

    suspend fun idle() = awaitHistory { !model.state.value.busy && !model.state.value.loading }

    fun close() {
        model.close()
        base.close()
        gateway.close()
        store.releaseReads()
    }
}

internal fun uploadedAvatar(
    ownerId: Long = 1,
    id: String = "main",
    version: Char = 'a',
): ChatAvatarResource {
    val hash =
        MessageDigest
            .getInstance("SHA-256")
            .digest(id.toByteArray())
            .joinToString("") { "%02x".format(it) }
            .take(24)
    return ChatAvatarResource("/static/avatars/ai_${ownerId}_${hash}_${version.toString().repeat(32)}.png")
}

internal suspend fun withAvatar(
    scope: CoroutineScope,
    block: suspend (AvatarHarness) -> Unit,
) {
    val harness = AvatarHarness(scope)
    try {
        block(harness)
    } finally {
        harness.close()
    }
}
