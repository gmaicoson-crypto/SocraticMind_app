package com.gmaicoson.socraticmind.avatarui

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import android.os.CancellationSignal
import com.gmaicoson.socraticmind.chat.AvatarImageFormat
import com.gmaicoson.socraticmind.chat.ChatAvatarResource
import com.gmaicoson.socraticmind.chat.images.AvatarImagePolicy
import com.gmaicoson.socraticmind.chat.images.DecodedAvatar
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

internal data class PreparedAvatar(
    val bytes: ByteArray,
    val format: AvatarImageFormat = AvatarImageFormat.PNG,
)

internal object AvatarImageCodec {
    suspend fun thumbnail(bytes: ByteArray): DecodedAvatar<Bitmap> =
        withContext(Dispatchers.Default) {
            require(bytes.size in 1..ChatAvatarResource.MAXIMUM_IMAGE_BYTES)
            val bitmap = decode(bytes, AvatarImagePolicy.DISPLAY_EDGE)
            try {
                currentCoroutineContext().ensureActive()
                DecodedAvatar(bitmap, bitmap.allocationByteCount)
            } catch (error: Throwable) {
                bitmap.recycle()
                throw error
            }
        }

    /** Cancellation closes the selected stream and cancels a provider that is still opening it. */
    suspend fun prepare(
        resolver: ContentResolver,
        uri: Uri,
    ): PreparedAvatar =
        suspendCancellableCoroutine { result ->
            val signal = CancellationSignal()
            val input = AtomicReference<InputStream?>()
            val job =
                CoroutineScope(Dispatchers.IO).launch(start = CoroutineStart.LAZY) {
                    try {
                        require(uri.scheme == ContentResolver.SCHEME_CONTENT)
                        val context = currentCoroutineContext()
                        val bytes =
                            requireNotNull(resolver.openAssetFileDescriptor(uri, "r", signal)).use { descriptor ->
                                require(descriptor.length <= AvatarImagePolicy.MAXIMUM_SOURCE_BYTES)
                                descriptor.createInputStream().use { stream ->
                                    input.set(stream)
                                    AvatarImagePolicy.read(stream) { context.ensureActive() }
                                }
                            }
                        input.set(null)
                        context.ensureActive()
                        val bitmap = decode(bytes, AvatarImagePolicy.UPLOAD_EDGE)
                        val prepared =
                            try {
                                context.ensureActive()
                                val encoded = ByteArrayOutputStream()
                                check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, encoded))
                                val data = encoded.toByteArray()
                                require(data.size in 1..ChatAvatarResource.MAXIMUM_IMAGE_BYTES)
                                PreparedAvatar(data)
                            } finally {
                                bitmap.recycle()
                            }
                        context.ensureActive()
                        result.resume(prepared)
                    } catch (error: Exception) {
                        result.resumeWithException(error)
                    } finally {
                        input.set(null)
                    }
                }
            result.invokeOnCancellation {
                signal.cancel()
                runCatching { input.getAndSet(null)?.close() }
                job.cancel()
            }
            job.start()
        }

    private fun decode(
        bytes: ByteArray,
        edge: Int,
    ): Bitmap {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        val plan = AvatarImagePolicy.plan(bounds.outWidth, bounds.outHeight, edge)
        val options =
            BitmapFactory.Options().apply {
                inSampleSize = plan.sampleSize
                inPreferredConfig = Bitmap.Config.ARGB_8888
                inScaled = false
            }
        var image = requireNotNull(BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options))
        try {
            require(image.width <= edge * 2 && image.height <= edge * 2)
            val orientation =
                runCatching {
                    bytes.inputStream().use { ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, 1) }
                }.getOrDefault(1)
            val transform =
                when (orientation) {
                    2 -> floatArrayOf(-1f, 0f, 0f, 0f, 1f, 0f, 0f, 0f, 1f)
                    3 -> floatArrayOf(-1f, 0f, 0f, 0f, -1f, 0f, 0f, 0f, 1f)
                    4 -> floatArrayOf(1f, 0f, 0f, 0f, -1f, 0f, 0f, 0f, 1f)
                    5 -> floatArrayOf(0f, 1f, 0f, 1f, 0f, 0f, 0f, 0f, 1f)
                    6 -> floatArrayOf(0f, -1f, 0f, 1f, 0f, 0f, 0f, 0f, 1f)
                    7 -> floatArrayOf(0f, -1f, 0f, -1f, 0f, 0f, 0f, 0f, 1f)
                    8 -> floatArrayOf(0f, 1f, 0f, -1f, 0f, 0f, 0f, 0f, 1f)
                    else -> null
                }
            if (transform != null) {
                val oriented =
                    Bitmap.createBitmap(
                        image,
                        0,
                        0,
                        image.width,
                        image.height,
                        Matrix().apply { setValues(transform) },
                        true,
                    )
                if (oriented !== image) {
                    image.recycle()
                    image = oriented
                }
            }
            val target = AvatarImagePolicy.plan(image.width, image.height, edge)
            if (image.width != target.width || image.height != target.height) {
                val scaled = Bitmap.createScaledBitmap(image, target.width, target.height, true)
                if (scaled !== image) {
                    image.recycle()
                    image = scaled
                }
            }
            return image
        } catch (error: Throwable) {
            image.recycle()
            throw error
        }
    }
}
