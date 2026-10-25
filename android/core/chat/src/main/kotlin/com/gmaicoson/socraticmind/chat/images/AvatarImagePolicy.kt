package com.gmaicoson.socraticmind.chat.images

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.InterruptedIOException
import kotlin.math.max

data class AvatarDecodePlan(
    val sampleSize: Int,
    val width: Int,
    val height: Int,
)

object AvatarImagePolicy {
    const val MAXIMUM_SOURCE_BYTES = 20 * 1024 * 1024
    const val DISPLAY_EDGE = 256
    const val UPLOAD_EDGE = 512
    const val MAXIMUM_EDGE = 16384
    const val MAXIMUM_PIXELS = 64L * 1024 * 1024

    fun plan(
        width: Int,
        height: Int,
        edge: Int,
    ): AvatarDecodePlan {
        require(width in 1..MAXIMUM_EDGE && height in 1..MAXIMUM_EDGE)
        require(width.toLong() * height <= MAXIMUM_PIXELS)
        require(edge in 1..UPLOAD_EDGE)
        val longest = max(width, height)
        var sample = 1
        while (longest / (sample * 2) >= edge) sample *= 2
        val scale = minOf(1.0, edge.toDouble() / longest)
        return AvatarDecodePlan(sample, max(1, (width * scale).toInt()), max(1, (height * scale).toInt()))
    }

    /** Use on an IO worker. The byte count is checked independently of provider metadata. */
    fun read(
        input: InputStream,
        checkCancelled: () -> Unit = {
            if (Thread.currentThread().isInterrupted) throw InterruptedIOException("Image read cancelled")
        },
    ): ByteArray {
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(64 * 1024)
        while (true) {
            checkCancelled()
            val count = input.read(buffer, 0, minOf(buffer.size, MAXIMUM_SOURCE_BYTES - output.size() + 1))
            if (count < 0) break
            require(count > 0) { "Image provider made no progress" }
            require(output.size() + count <= MAXIMUM_SOURCE_BYTES) { "Image source exceeds byte budget" }
            output.write(buffer, 0, count)
        }
        require(output.size() > 0) { "Empty image" }
        return output.toByteArray()
    }
}
