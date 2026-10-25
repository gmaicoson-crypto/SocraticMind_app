package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.chat.images.AvatarDecodePlan
import com.gmaicoson.socraticmind.chat.images.AvatarImagePolicy
import kotlinx.coroutines.CancellationException
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.InputStream

class AvatarImagePolicyTest {
    @Test fun `sampling bounds intermediate allocation and preserves aspect`() {
        assertEquals(AvatarDecodePlan(1, 20, 10), AvatarImagePolicy.plan(20, 10, 256))
        assertEquals(AvatarDecodePlan(16, 512, 256), AvatarImagePolicy.plan(10000, 5000, 512))
        for (side in listOf(1, 255, 256, 257, 511, 512, 1025, 8192, 16384)) {
            val plan = AvatarImagePolicy.plan(side, 1, 256)
            assertTrue(plan.width in 1..256 && plan.height == 1)
            assertTrue(side / plan.sampleSize <= 512)
            assertEquals(0, plan.sampleSize and (plan.sampleSize - 1))
        }
    }

    @Test fun `dimensions reject overflow and excessive source pixels before decoding`() {
        AvatarImagePolicy.plan(8192, 8192, 512)
        for ((width, height) in listOf(
            0 to 1,
            -1 to 1,
            Int.MAX_VALUE to Int.MAX_VALUE,
            16385 to 1,
            8193 to 8193,
        )) {
            assertThrows(IllegalArgumentException::class.java) { AvatarImagePolicy.plan(width, height, 256) }
        }
        for (edge in listOf(0, 513)) {
            assertThrows(IllegalArgumentException::class.java) { AvatarImagePolicy.plan(1, 1, edge) }
        }
    }

    @Test fun `read enforces actual bytes and stops immediately beyond the budget`() {
        val exact = CountingSource(AvatarImagePolicy.MAXIMUM_SOURCE_BYTES)
        assertEquals(AvatarImagePolicy.MAXIMUM_SOURCE_BYTES, AvatarImagePolicy.read(exact).size)
        val tooLarge = CountingSource(AvatarImagePolicy.MAXIMUM_SOURCE_BYTES + 100000)
        assertThrows(IllegalArgumentException::class.java) { AvatarImagePolicy.read(tooLarge) }
        assertEquals(AvatarImagePolicy.MAXIMUM_SOURCE_BYTES + 1, tooLarge.read)
    }

    @Test fun `empty stalled and cancelled providers fail without reading the remainder`() {
        assertThrows(IllegalArgumentException::class.java) { AvatarImagePolicy.read(byteArrayOf().inputStream()) }
        val stalled =
            object : InputStream() {
                override fun read(): Int = 0

                override fun read(
                    bytes: ByteArray,
                    offset: Int,
                    length: Int,
                ): Int = 0
            }
        assertThrows(IllegalArgumentException::class.java) { AvatarImagePolicy.read(stalled) }
        val source = CountingSource(1000000)
        var checks = 0
        assertThrows(CancellationException::class.java) {
            AvatarImagePolicy.read(source) { if (++checks == 2) throw CancellationException() }
        }
        assertEquals(64 * 1024, source.read)
    }
}

private class CountingSource(
    private val size: Int,
) : InputStream() {
    var read = 0
        private set

    override fun read(): Int =
        if (read >= size) {
            -1
        } else {
            read++
            7
        }

    override fun read(
        bytes: ByteArray,
        offset: Int,
        length: Int,
    ): Int {
        if (read >= size) return -1
        val count = minOf(length, size - read)
        bytes.fill(7, offset, offset + count)
        read += count
        return count
    }
}
