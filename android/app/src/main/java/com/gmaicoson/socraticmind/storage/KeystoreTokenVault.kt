package com.gmaicoson.socraticmind.storage

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import com.gmaicoson.socraticmind.auth.EncryptedTokenVault
import com.gmaicoson.socraticmind.auth.TokenVault
import com.gmaicoson.socraticmind.auth.VaultBlob
import com.gmaicoson.socraticmind.auth.VaultException
import com.gmaicoson.socraticmind.auth.VaultKeys
import com.gmaicoson.socraticmind.network.ApiEndpoint
import java.io.File
import java.io.FileNotFoundException
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** Construct once per backend and call through SessionStore's IO dispatcher. */
fun keystoreTokenVault(
    context: Context,
    endpoint: ApiEndpoint,
): TokenVault {
    val identity =
        MessageDigest
            .getInstance("SHA-256")
            .digest(endpoint.credentialScope.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    return EncryptedTokenVault(
        endpoint.credentialScope,
        AndroidVaultKeys("com.gmaicoson.socraticmind.session.$identity"),
        AtomicVaultBlob(File(context.noBackupFilesDir, "session-$identity.bin")),
    )
}

private class AndroidVaultKeys(
    private val alias: String,
) : VaultKeys {
    private fun store() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    override fun existing(): SecretKey? = store().getKey(alias, null) as SecretKey?

    override fun create(): SecretKey {
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec
                .Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return generator.generateKey()
    }

    override fun delete() = store().deleteEntry(alias)
}

private class AtomicVaultBlob(
    private val file: File,
) : VaultBlob {
    private val atomic = AtomicFile(file)

    override fun read(): ByteArray? {
        val stream =
            try {
                atomic.openRead()
            } catch (error: FileNotFoundException) {
                if (file.exists() || File(file.path + ".bak").exists()) throw error
                return null
            }
        return stream.use { input ->
            val bytes = ByteArray(EncryptedTokenVault.MAX_ENVELOPE_BYTES + 1)
            var count = 0
            while (count < bytes.size) {
                val size = input.read(bytes, count, bytes.size - count)
                if (size < 0) break
                count += size
            }
            if (count > EncryptedTokenVault.MAX_ENVELOPE_BYTES) throw VaultException()
            bytes.copyOf(count)
        }
    }

    override fun write(bytes: ByteArray) {
        val stream = atomic.startWrite()
        try {
            stream.write(bytes)
            stream.fd.sync()
            atomic.finishWrite(stream)
        } catch (error: Exception) {
            atomic.failWrite(stream)
            throw error
        }
        if (read()?.contentEquals(bytes) != true) throw VaultException()
    }

    override fun delete() {
        atomic.delete()
        if (listOf(file, File(file.path + ".bak"), File(file.path + ".new")).any { it.exists() }) {
            throw VaultException()
        }
    }
}
