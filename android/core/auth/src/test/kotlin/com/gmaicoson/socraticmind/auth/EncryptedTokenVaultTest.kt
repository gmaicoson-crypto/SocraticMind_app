package com.gmaicoson.socraticmind.auth

import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import java.io.IOException
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

class EncryptedTokenVaultTest {
    @Test
    fun encryptedRoundTripSurvivesOwnerRecreationAndUsesFreshNonce() {
        val keys = TestKeys()
        val blob = TestBlob()
        val first = EncryptedTokenVault(SCOPE, keys, blob)
        assertNull(first.read())
        assertEquals(0, keys.creations)
        first.write(TOKEN)
        val original = checkNotNull(blob.value).copyOf()
        assertFalse(original.toString(Charsets.UTF_8).contains(TOKEN))
        val next = EncryptedTokenVault(SCOPE, keys, blob)
        assertEquals(TOKEN, next.read())
        next.write(TOKEN)
        assertNotEquals(original.toList(), checkNotNull(blob.value).toList())
        assertEquals(TOKEN, next.read())
        assertEquals(1, keys.creations)
    }

    @Test
    fun movedOrCorruptedCiphertextFailsWithoutSilentlyDeletingCredentials() {
        val keys = TestKeys()
        val blob = TestBlob()
        val vault = EncryptedTokenVault(SCOPE, keys, blob)
        vault.write(TOKEN)
        val original = checkNotNull(blob.value).copyOf()
        assertThrows(Exception::class.java) { EncryptedTokenVault(SCOPE + "other/", keys, blob).read() }
        assertArrayEquals(original, blob.value)
        for (damaged in listOf(
            original.copyOf().apply { this[lastIndex] = (last().toInt() xor 1).toByte() },
            original.copyOf().apply { this[0] = 2 },
            original.copyOf(20),
            ByteArray(EncryptedTokenVault.MAX_ENVELOPE_BYTES + 1),
        )) {
            blob.value = damaged
            assertThrows(Exception::class.java) { vault.read() }
            assertArrayEquals(damaged, blob.value)
        }
        blob.value = original
        assertEquals(TOKEN, vault.read())
    }

    @Test
    fun missingKeyNeverGeneratesAReplacementDuringRead() {
        val keys = TestKeys()
        val blob = TestBlob()
        val vault = EncryptedTokenVault(SCOPE, keys, blob)
        vault.write(TOKEN)
        keys.key = null
        val before = checkNotNull(blob.value).copyOf()
        assertThrows(VaultException::class.java) { vault.read() }
        assertEquals(1, keys.creations)
        assertArrayEquals(before, blob.value)
        vault.clear()
        assertNull(vault.read())
    }

    @Test
    fun clearTriesBothResourcesAndReportsIncompleteCleanup() {
        for (keyFailure in listOf(true, false)) {
            val keys = TestKeys()
            val blob = TestBlob()
            val vault = EncryptedTokenVault(SCOPE, keys, blob)
            vault.write(TOKEN)
            keys.failDelete = keyFailure
            blob.failDelete = !keyFailure
            assertThrows(VaultException::class.java) { vault.clear() }
            assertEquals(1, keys.deletions)
            assertEquals(1, blob.deletions)
            if (keyFailure) assertNull(blob.value) else assertNull(keys.key)
            keys.failDelete = false
            blob.failDelete = false
            vault.clear()
            vault.clear()
            assertNull(vault.read())
        }
    }

    @Test
    fun failedPersistenceDoesNotFallBackToPlaintextOrClaimSuccess() {
        val blob = TestBlob().apply { failWrite = true }
        val vault = EncryptedTokenVault(SCOPE, TestKeys(), blob)
        assertThrows(IOException::class.java) { vault.write(TOKEN) }
        assertNull(blob.value)
    }

    @Test
    fun invalidOrOversizedTokensAreRejectedBeforeCreatingStorage() {
        val keys = TestKeys()
        val blob = TestBlob()
        val vault = EncryptedTokenVault(SCOPE, keys, blob)
        for (token in listOf("", "  ", "a\nb", "a\rb", "x".repeat(16 * 1024 + 1), "中".repeat(6000))) {
            assertThrows(VaultException::class.java) { vault.write(token) }
        }
        assertEquals(0, keys.creations)
        assertNull(blob.value)
    }

    private class TestKeys : VaultKeys {
        var key: SecretKey? = null
        var creations = 0
        var deletions = 0
        var failDelete = false

        override fun existing() = key

        override fun create(): SecretKey {
            creations++
            return KeyGenerator
                .getInstance("AES")
                .apply { init(256) }
                .generateKey()
                .also { key = it }
        }

        override fun delete() {
            deletions++
            if (failDelete) throw IOException("synthetic key removal failure")
            key = null
        }
    }

    private class TestBlob : VaultBlob {
        var value: ByteArray? = null
        var failWrite = false
        var failDelete = false
        var deletions = 0

        override fun read() = value?.copyOf()

        override fun write(bytes: ByteArray) {
            if (failWrite) throw IOException("synthetic disk failure")
            value = bytes.copyOf()
        }

        override fun delete() {
            deletions++
            if (failDelete) throw IOException("synthetic blob removal failure")
            value = null
        }
    }

    companion object {
        private const val SCOPE = "https://api.example.test/mobile/"
        private const val TOKEN = "synthetic-token-中文"
    }
}
