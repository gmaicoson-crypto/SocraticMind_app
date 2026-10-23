package com.gmaicoson.socraticmind.chat

import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files

class FileChatTurnJournalTest {
    @Test
    fun `schema one remains readable and regeneration identity survives schema two reopen`() =
        runBlocking {
            val directory = Files.createTempDirectory("chat-journal-version").toFile()
            try {
                val journal = FileChatTurnJournal(directory, "scope")
                val ordinary = turnRequest().pending
                journal.save(ordinary)
                val file = directory.walkTopDown().single { it.isFile }
                file.writeText(file.readText().replace("\"schema\":2", "\"schema\":1"))
                assertEquals(ordinary, journal.read(1))
                journal.clear(ordinary)
                val regeneration = ordinary.copy(regenerateMessageId = 102)
                journal.save(regeneration)
                assertTrue(file.readText().contains("\"schema\":2"))
                assertEquals(regeneration, FileChatTurnJournal(directory, "scope").read(1))
                assertTrue(runCatching { journal.clear(ordinary) }.isFailure)
                assertEquals(regeneration, journal.read(1))
            } finally {
                directory.deleteRecursively()
            }
        }

    @Test
    fun `reopen preserves only identifiers with endpoint and owner isolation`() =
        runBlocking {
            val directory = Files.createTempDirectory("chat-journal").toFile()
            try {
                val pending = turnRequest().pending
                val journal = FileChatTurnJournal(directory, "https://example.test/")
                journal.save(pending)
                val second = pending.copy(ownerId = 2, requestId = "other")
                journal.save(second)
                assertEquals(pending, FileChatTurnJournal(directory, "https://example.test/").read(1))
                assertEquals(second, journal.read(2))
                assertNull(FileChatTurnJournal(directory, "https://other.test/").read(1))
                val contents =
                    directory
                        .walkTopDown()
                        .filter { it.isFile }
                        .map { it.readText() }
                        .toList()
                assertEquals(2, contents.size)
                assertTrue(
                    contents.none {
                        it.contains("user_input") || it.contains("access_token") ||
                            it.contains("为什么")
                    },
                )
                journal.clear(pending)
                assertNull(journal.read(1))
                assertEquals(second, journal.read(2))
            } finally {
                directory.deleteRecursively()
            }
        }

    @Test
    fun `different pending save and stale clear cannot erase recovery`() =
        runBlocking {
            val directory = Files.createTempDirectory("chat-journal").toFile()
            try {
                val journal = FileChatTurnJournal(directory, "scope")
                val pending = turnRequest().pending
                journal.save(pending)
                journal.save(pending)
                val newer = pending.copy(requestId = "different")
                assertTrue(runCatching { journal.save(newer) }.isFailure)
                assertTrue(runCatching { journal.clear(newer) }.isFailure)
                assertEquals(pending, journal.read(1))
            } finally {
                directory.deleteRecursively()
            }
        }

    @Test
    fun `corrupt oversized and owner-mismatched records fail closed`() =
        runBlocking {
            val directory = Files.createTempDirectory("chat-journal").toFile()
            try {
                val journal = FileChatTurnJournal(directory, "scope")
                val pending = turnRequest().pending
                journal.save(pending)
                val file = directory.walkTopDown().single { it.isFile }
                val original = file.readText()
                for (bad in listOf("{", "x".repeat(4097), original.replace("\"owner_id\":1", "\"owner_id\":2"))) {
                    file.writeText(bad)
                    assertTrue(runCatching { journal.read(1) }.isFailure)
                    assertTrue(runCatching { journal.save(pending) }.isFailure)
                    assertEquals(bad, file.readText())
                }
            } finally {
                directory.deleteRecursively()
            }
        }

    @Test
    fun `unwritable directory fails without creating a valid record`() =
        runBlocking {
            val file = Files.createTempFile("chat-journal", ".file").toFile()
            try {
                assertTrue(runCatching { FileChatTurnJournal(file, "scope").save(turnRequest().pending) }.isFailure)
            } finally {
                file.delete()
            }
        }
}
