package com.gmaicoson.socraticmind.learning

import com.gmaicoson.socraticmind.storage.AccountFileStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File

/** One app-scoped instance per backend; the host supplies a private, backup-excluded directory. */
class FileOnboardingJournal(
    directory: File,
    endpointScope: String,
) : OnboardingJournal {
    private val storage = AccountFileStorage(directory, endpointScope, "onboarding", 4096)
    private val mutex = Mutex()

    override suspend fun read(ownerId: Long): PendingOnboarding? =
        withContext(Dispatchers.IO) { mutex.withLock { readFile(ownerId) } }

    override suspend fun save(pending: PendingOnboarding) =
        withContext(Dispatchers.IO) {
            mutex.withLock {
                val previous = readFile(pending.ownerId)
                require(previous == null || previous == pending) { "Pending learning run exists" }
                if (previous == pending) return@withLock
                val bytes =
                    buildJsonObject {
                        put("schema", 1)
                        put("owner_id", pending.ownerId)
                        put("run_id", pending.runId.value)
                        put("confirmation_id", pending.confirmationId.value)
                    }.toString().toByteArray(Charsets.UTF_8)
                storage.write(pending.ownerId, bytes)
                check(readFile(pending.ownerId) == pending) { "Learning recovery write failed" }
            }
        }

    override suspend fun clear(pending: PendingOnboarding) =
        withContext(Dispatchers.IO) {
            mutex.withLock {
                val previous = readFile(pending.ownerId)
                require(previous == null || previous == pending) { "Learning recovery record changed" }
                storage.remove(pending.ownerId)
                check(readFile(pending.ownerId) == null)
            }
        }

    private fun readFile(ownerId: Long): PendingOnboarding? {
        val bytes = storage.read(ownerId) ?: return null
        val row = Json.parseToJsonElement(bytes.decodeToString(throwOnInvalidSequence = true)).obj()
        require(row.number("schema", 1, 1) == 1L)
        return PendingOnboarding(
            row.number("owner_id", 1, 9_007_199_254_740_991).also { require(it == ownerId) },
            OnboardingID(row.text("run_id", 36)),
            OnboardingID(row.text("confirmation_id", 36)),
        )
    }
}
