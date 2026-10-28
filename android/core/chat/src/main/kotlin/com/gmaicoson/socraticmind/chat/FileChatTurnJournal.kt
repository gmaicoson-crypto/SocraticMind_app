package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.storage.AccountFileStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File

/** App-private, excluded-from-backup directory supplied by the host. One app-scoped instance per endpoint. */
class FileChatTurnJournal(
    directory: File,
    endpointScope: String,
) : ChatTurnJournal {
    private val storage = AccountFileStorage(directory, endpointScope, "chat-turns", MAX_BYTES)
    private val mutex = Mutex()

    override suspend fun read(ownerId: Long): PendingChatTurn? =
        withContext(Dispatchers.IO) { mutex.withLock { readFile(ownerId) } }

    override suspend fun save(pending: PendingChatTurn) =
        withContext(Dispatchers.IO) {
            mutex.withLock {
                val existing = readFile(pending.ownerId)
                require(existing == null || existing == pending) { "Unconfirmed chat turn exists" }
                if (existing == pending) return@withLock
                storage.write(pending.ownerId, encode(pending).toByteArray(Charsets.UTF_8))
                check(readFile(pending.ownerId) == pending) { "Recovery write could not be verified" }
            }
        }

    override suspend fun clear(pending: PendingChatTurn) =
        withContext(Dispatchers.IO) {
            mutex.withLock {
                val existing = readFile(pending.ownerId)
                require(existing == null || existing == pending) { "Recovery record changed" }
                storage.remove(pending.ownerId)
                check(readFile(pending.ownerId) == null)
            }
        }

    private fun readFile(ownerId: Long): PendingChatTurn? {
        val bytes = storage.read(ownerId) ?: return null
        val value =
            Json
                .parseToJsonElement(
                    bytes.decodeToString(throwOnInvalidSequence = true),
                ).historyObject()
        require(value.historyLong("schema") in 1L..2L)
        val target = value.getValue("target").historyObject()
        return PendingChatTurn(
            ownerId = value.historyLong("owner_id").also { require(it == ownerId) },
            target =
                ChatTarget(
                    target.historyString("session_id"),
                    ChatMode.entries.single { it.wireValue == target.historyString("mode") },
                    target.historyString("node_key"),
                    target.historyLong("topic_id"),
                ),
            requestId = value.historyString("request_id"),
            regenerateMessageId =
                if (value.containsKey("regenerate_message_id")) {
                    value.historyOptionalLong("regenerate_message_id")
                } else {
                    null
                },
        )
    }

    private fun encode(pending: PendingChatTurn): String =
        buildJsonObject {
            put("schema", 2)
            put("owner_id", pending.ownerId)
            put("request_id", pending.requestId)
            pending.regenerateMessageId?.let { put("regenerate_message_id", it) }
            put(
                "target",
                buildJsonObject {
                    put("session_id", pending.target.sessionId)
                    put("mode", pending.target.mode.wireValue)
                    put("node_key", pending.target.nodeKey)
                    put("topic_id", pending.target.topicId)
                },
            )
        }.toString()

    private companion object {
        const val MAX_BYTES = 4096
    }
}
