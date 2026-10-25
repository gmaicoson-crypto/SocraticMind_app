package com.gmaicoson.socraticmind.avatarui

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gmaicoson.socraticmind.chat.ChatAvatarResource
import com.gmaicoson.socraticmind.chat.images.AvatarImageLoader
import kotlinx.coroutines.CancellationException

data class AvatarPresentation(
    val images: AvatarImageLoader<Bitmap>?,
    val resource: ChatAvatarResource,
    val fallback: ChatAvatarResource,
)

private data class AvatarFrame(
    val source: AvatarPresentation,
    val image: Bitmap,
)

@Composable
fun AvatarImage(
    source: AvatarPresentation,
    size: Dp = 40.dp,
    description: String? = null,
) {
    val frame by produceState<AvatarFrame?>(null, source) {
        value = null
        val images = source.images ?: return@produceState
        val image =
            try {
                images.load(source.resource)
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                if (source.resource == source.fallback) {
                    null
                } else {
                    try {
                        images.load(source.fallback)
                    } catch (fallbackError: Exception) {
                        if (fallbackError is CancellationException) throw fallbackError
                        null
                    }
                }
            }
        if (image != null) value = AvatarFrame(source, image)
    }
    Box(
        Modifier
            .size(size)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.secondaryContainer)
            .clearAndSetSemantics { if (description != null) contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        val image = frame?.takeIf { it.source == source }?.image
        if (image == null) {
            Text("AI", color = MaterialTheme.colorScheme.onSecondaryContainer)
        } else {
            Image(
                image.asImageBitmap(),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.size(size),
            )
        }
    }
}
