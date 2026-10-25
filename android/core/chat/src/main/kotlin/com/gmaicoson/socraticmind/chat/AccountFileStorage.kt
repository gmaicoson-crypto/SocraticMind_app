package com.gmaicoson.socraticmind.chat

import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/** Bounded atomic IO shared by account records. The calling repository owns synchronization and schema. */
internal class AccountFileStorage(
    directory: File,
    endpointScope: String,
    namespace: String,
    private val maximumBytes: Int,
) {
    private val directory: File

    init {
        require(endpointScope.isNotBlank() && namespace.matches(Regex("[a-z-]+")) && maximumBytes > 0)
        val hash =
            MessageDigest
                .getInstance("SHA-256")
                .digest(endpointScope.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
        this.directory = File(directory, "$namespace-$hash")
    }

    fun read(ownerId: Long): ByteArray? {
        val path = file(ownerId)
        if (!path.exists()) return null
        val bytes = ByteArray(maximumBytes + 1)
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
        require(count in 1..maximumBytes) { "Invalid account record size" }
        return bytes.copyOf(count)
    }

    fun write(
        ownerId: Long,
        bytes: ByteArray,
    ) {
        require(bytes.size in 1..maximumBytes)
        val destination = file(ownerId)
        check(directory.isDirectory || directory.mkdirs()) { "Cannot create account record directory" }
        val temporary = File(directory, "$ownerId.tmp")
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
            check(read(ownerId)?.contentEquals(bytes) == true) { "Account write could not be verified" }
        } finally {
            Files.deleteIfExists(temporary.toPath())
        }
    }

    fun remove(ownerId: Long) {
        Files.deleteIfExists(file(ownerId).toPath())
        check(read(ownerId) == null)
    }

    private fun file(ownerId: Long): File {
        require(ownerId > 0)
        return File(directory, "$ownerId.json")
    }
}
