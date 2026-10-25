package com.gmaicoson.socraticmind.chat

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File

/** Account-local choices only. Supply the same private, backup-excluded host directory as the turn journal. */
class FileChatAvatarStore(
    directory: File,
    endpointScope: String,
) : ChatAvatarStore {
    private val storage = AccountFileStorage(directory, endpointScope, "chat-avatars", 512 * 1024)
    private val mutex = Mutex()

    override suspend fun read(ownerId: Long): Map<String, ChatAvatarResource> =
        withContext(Dispatchers.IO) { mutex.withLock { readFile(ownerId) } }

    override suspend fun replace(
        ownerId: Long,
        sessionId: String,
        expected: ChatAvatarResource?,
        value: ChatAvatarResource?,
    ) = withContext(Dispatchers.IO) {
        mutex.withLock {
            requireSessionId(sessionId)
            require(sessionId == sessionId.trim())
            require(value?.belongsTo(ownerId, sessionId) != false)
            val previous = readFile(ownerId)
            if (previous[sessionId] != expected) throw ChatAvatarException(ChatAvatarFailure.CONFLICT)
            if (expected == value) return@withLock
            val choices = previous.toMutableMap()
            if (value == null) choices.remove(sessionId) else choices[sessionId] = value
            if (choices.size > 1000) throw ChatAvatarException(ChatAvatarFailure.CAPACITY)
            val bytes =
                buildJsonObject {
                    put("schema", 1)
                    put("owner_id", ownerId)
                    put(
                        "choices",
                        buildJsonArray {
                            choices.toSortedMap().forEach { (id, resource) ->
                                add(
                                    buildJsonObject {
                                        put("session_id", id)
                                        put("path", resource.path)
                                    },
                                )
                            }
                        },
                    )
                }.toString().toByteArray(Charsets.UTF_8)
            if (bytes.size > 512 * 1024) throw ChatAvatarException(ChatAvatarFailure.CAPACITY)
            storage.write(ownerId, bytes)
        }
    }

    override suspend fun clear(ownerId: Long) =
        withContext(Dispatchers.IO) { mutex.withLock { storage.remove(ownerId) } }

    private fun readFile(ownerId: Long): Map<String, ChatAvatarResource> {
        val bytes = storage.read(ownerId) ?: return emptyMap()
        val record = Json.parseToJsonElement(bytes.decodeToString(throwOnInvalidSequence = true)).historyObject()
        if (record.historyLong("schema") != 1L || record.historyLong("owner_id") != ownerId) {
            throw ChatAvatarException(ChatAvatarFailure.INVALID_RECORD)
        }
        val choices = record.historyArray("choices")
        if (choices.size > 1000) throw ChatAvatarException(ChatAvatarFailure.INVALID_RECORD)
        val values =
            choices
                .map { value ->
                    val row = value.historyObject()
                    val id = row.historyString("session_id")
                    id to ChatAvatarResource(row.historyString("path")).also { require(it.belongsTo(ownerId, id)) }
                }.toMap()
        if (values.size != choices.size) throw ChatAvatarException(ChatAvatarFailure.INVALID_RECORD)
        return values
    }
}
