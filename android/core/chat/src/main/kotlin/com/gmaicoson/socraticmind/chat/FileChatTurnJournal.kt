package com.gmaicoson.socraticmind.chat

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/** App-private, excluded-from-backup directory supplied by the host. One app-scoped instance per endpoint. */
class FileChatTurnJournal(
    directory: File,
    endpointScope: String,
) : ChatTurnJournal {
    private val directory = File(directory, "chat-turns-${scopeHash(endpointScope)}")
    private val mutex = Mutex()

    override suspend fun read(ownerId: Long): PendingChatTurn? =
        withContext(Dispatchers.IO) { mutex.withLock { readFile(ownerId) } }

    override suspend fun save(pending: PendingChatTurn) =
        withContext(Dispatchers.IO) {
            mutex.withLock {
                val existing = readFile(pending.ownerId)
                require(existing == null || existing == pending) { "Unconfirmed chat turn exists" }
                if (existing == pending) return@withLock
                check(directory.isDirectory || directory.mkdirs()) { "Cannot create recovery directory" }
                val destination = file(pending.ownerId)
                val temporary = File(directory, "${pending.ownerId}.tmp")
                val bytes = encode(pending).toByteArray(Charsets.UTF_8)
                require(bytes.size <= MAX_BYTES)
                try {
                    FileOutputStream(temporary).use { output ->
                        output.write(bytes)
                        output.fd.sync()
                    }
                    Files.move(
                        temporary.toPath(),
                        destination.toPath(),
                        StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING,
                    )
                    check(readFile(pending.ownerId) == pending) { "Recovery write could not be verified" }
                } finally {
                    Files.deleteIfExists(temporary.toPath())
                }
            }
        }

    override suspend fun clear(pending: PendingChatTurn) =
        withContext(Dispatchers.IO) {
            mutex.withLock {
                val existing = readFile(pending.ownerId)
                require(existing == null || existing == pending) { "Recovery record changed" }
                Files.deleteIfExists(file(pending.ownerId).toPath())
                check(readFile(pending.ownerId) == null)
            }
        }

    private fun file(ownerId: Long): File {
        require(ownerId > 0)
        return File(directory, "$ownerId.json")
    }

    private fun readFile(ownerId: Long): PendingChatTurn? {
        val path = file(ownerId)
        if (!path.exists()) return null
        val bytes = ByteArray(MAX_BYTES + 1)
        val count =
            path.inputStream().use { input ->
                var offset = 0
                while (offset < bytes.size) {
                    val read = input.read(bytes, offset, bytes.size - offset)
                    if (read < 0) break
                    offset += read
                }
                offset
            }
        require(count in 1..MAX_BYTES) { "Invalid recovery record size" }
        val value =
            Json
                .parseToJsonElement(
                    bytes.decodeToString(0, count, throwOnInvalidSequence = true),
                ).historyObject()
        require(value.historyLong("schema") == 1L)
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
        )
    }

    private fun encode(pending: PendingChatTurn): String =
        buildJsonObject {
            put("schema", 1)
            put("owner_id", pending.ownerId)
            put("request_id", pending.requestId)
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

    private fun scopeHash(value: String): String {
        require(value.isNotBlank())
        return MessageDigest
            .getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }

    private companion object {
        const val MAX_BYTES = 4096
    }
}
