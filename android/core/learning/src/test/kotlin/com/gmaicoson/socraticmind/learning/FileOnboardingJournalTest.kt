package com.gmaicoson.socraticmind.learning

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files

class FileOnboardingJournalTest {
    @Test
    fun `reopen keeps only stable identifiers isolated by owner backend and namespace`() =
        runBlocking {
            val root = Files.createTempDirectory("learning-journal").toFile()
            try {
                val journal = FileOnboardingJournal(root, "scope")
                val first = PendingOnboarding(1, OnboardingID.create(), OnboardingID.create())
                val second = first.copy(ownerId = 2, runId = OnboardingID.create())
                journal.save(first)
                journal.save(second)
                assertEquals(first, FileOnboardingJournal(root, "scope").read(1))
                assertNull(FileOnboardingJournal(root, "other").read(1))
                assertEquals(
                    setOf(
                        "schema",
                        "owner_id",
                        "run_id",
                        "confirmation_id",
                    ),
                    kotlinx.serialization.json.Json
                        .parseToJsonElement(
                            root
                                .walkTopDown()
                                .first {
                                    it.isFile
                                }.readText(),
                        ).obj()
                        .keys,
                )
                journal.clear(first)
                assertNull(journal.read(1))
                assertEquals(second, journal.read(2))
            } finally {
                root.deleteRecursively()
            }
        }

    @Test
    fun `stale save or clear cannot replace another pending transaction`() =
        runBlocking {
            val root = Files.createTempDirectory("learning-journal").toFile()
            try {
                val journal = FileOnboardingJournal(root, "scope")
                val first = PendingOnboarding(1, OnboardingID.create(), OnboardingID.create())
                val other = first.copy(confirmationId = OnboardingID.create())
                journal.save(first)
                journal.save(first)
                assertTrue(runCatching { journal.save(other) }.isFailure)
                assertTrue(runCatching { journal.clear(other) }.isFailure)
                assertEquals(first, journal.read(1))
            } finally {
                root.deleteRecursively()
            }
        }

    @Test
    fun `corrupt numeric schema oversized and mismatched records are never overwritten`() =
        runBlocking {
            val root = Files.createTempDirectory("learning-journal").toFile()
            try {
                val journal = FileOnboardingJournal(root, "scope")
                val pending = PendingOnboarding(1, OnboardingID.create(), OnboardingID.create())
                journal.save(pending)
                val file = root.walkTopDown().single { it.isFile }
                val original =
                    kotlinx.serialization.json.Json
                        .parseToJsonElement(file.readText())
                        .obj()
                val malformed =
                    listOf(
                        "{",
                        "x".repeat(4097),
                        "",
                        file.readText().replace("\"schema\":1", "\"schema\":1.0"),
                        JsonObject(original + ("owner_id" to JsonPrimitive(2))).toString(),
                        JsonObject(original + ("run_id" to JsonPrimitive("../"))).toString(),
                    )
                for (bytes in malformed.map { it.toByteArray() } + listOf(byteArrayOf(-1))) {
                    file.writeBytes(bytes)
                    assertTrue(runCatching { journal.read(1) }.isFailure)
                    assertTrue(runCatching { journal.save(pending) }.isFailure)
                    assertTrue(runCatching { journal.clear(pending) }.isFailure)
                    assertTrue(file.readBytes().contentEquals(bytes))
                }
            } finally {
                root.deleteRecursively()
            }
        }

    @Test
    fun `unwritable directory cannot claim a successful saved record`() =
        runBlocking {
            val file = Files.createTempFile("learning-journal", ".file").toFile()
            try {
                val journal = FileOnboardingJournal(file, "scope")
                assertTrue(
                    runCatching {
                        journal.save(
                            PendingOnboarding(1, OnboardingID.create(), OnboardingID.create()),
                        )
                    }.isFailure,
                )
            } finally {
                file.delete()
            }
        }
}
