package com.gmaicoson.socraticmind.auth

import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Platform IO is injected so corruption and isolation can be checked without an APK. */
interface VaultKeys {
    fun existing(): SecretKey?

    fun create(): SecretKey

    fun delete()
}

interface VaultBlob {
    fun read(): ByteArray?

    fun write(bytes: ByteArray)

    fun delete()
}

class VaultException : IllegalStateException("Credential storage unavailable")

/** AES-GCM binds each envelope to its backend; key material stays in the platform provider. */
class EncryptedTokenVault(
    backendIdentity: String,
    private val keys: VaultKeys,
    private val blob: VaultBlob,
) : TokenVault {
    private val context = "SocraticMind:TokenVault:v1:$backendIdentity".toByteArray(Charsets.UTF_8)

    @Synchronized
    override fun read(): String? {
        val envelope = blob.read() ?: return null
        if (envelope.size !in MIN_ENVELOPE_BYTES..MAX_ENVELOPE_BYTES || envelope[0] != VERSION) {
            throw VaultException()
        }
        val key = keys.existing() ?: throw VaultException()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, envelope.copyOfRange(1, 13)))
        cipher.updateAAD(context)
        val plaintext = cipher.doFinal(envelope, 13, envelope.size - 13)
        try {
            val token =
                Charsets.UTF_8
                    .newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(plaintext))
                    .toString()
            validate(token)
            return token
        } finally {
            plaintext.fill(0)
        }
    }

    @Synchronized
    override fun write(token: String) {
        validate(token)
        val plaintext = token.toByteArray(Charsets.UTF_8)
        try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, keys.existing() ?: keys.create())
            if (cipher.iv.size != 12) throw VaultException()
            cipher.updateAAD(context)
            blob.write(byteArrayOf(VERSION) + cipher.iv + cipher.doFinal(plaintext))
        } finally {
            plaintext.fill(0)
        }
    }

    @Synchronized
    override fun clear() {
        // Try both removals, even when the first fails. Never report a partial cleanup as success.
        var failed = false
        try {
            keys.delete()
        } catch (_: Exception) {
            failed = true
        }
        try {
            blob.delete()
        } catch (_: Exception) {
            failed = true
        }
        if (failed) throw VaultException()
    }

    private fun validate(token: String) {
        if (token.isBlank() || token.any { it == '\r' || it == '\n' } ||
            token.toByteArray(Charsets.UTF_8).size > MAX_TOKEN_BYTES
        ) {
            throw VaultException()
        }
    }

    companion object {
        private const val VERSION: Byte = 1
        private const val MAX_TOKEN_BYTES = 16 * 1024
        private const val MIN_ENVELOPE_BYTES = 30
        const val MAX_ENVELOPE_BYTES = MAX_TOKEN_BYTES + 29
    }
}
