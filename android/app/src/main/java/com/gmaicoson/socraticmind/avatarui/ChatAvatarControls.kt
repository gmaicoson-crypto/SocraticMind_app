package com.gmaicoson.socraticmind.avatarui

import android.graphics.Bitmap
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.gmaicoson.socraticmind.chat.ChatAvatarController
import com.gmaicoson.socraticmind.chat.ChatAvatarResource
import com.gmaicoson.socraticmind.chat.ChatAvatarState
import com.gmaicoson.socraticmind.chat.ChatTarget
import com.gmaicoson.socraticmind.chat.images.AvatarImageLoader

@Composable
fun ChatAvatarControls(
    model: ChatAvatarController,
    state: ChatAvatarState,
    images: AvatarImageLoader<Bitmap>?,
    target: ChatTarget?,
    enabled: Boolean,
) {
    Column(Modifier.padding(horizontal = 12.dp)) {
        if (target != null) {
            Row {
                AvatarImage(AvatarPresentation(images, state.resource(target), ChatAvatarResource.default(target.mode)))
                TextButton(
                    onClick = { model.open(target) },
                    enabled = enabled && state.loaded && !state.loading && !state.busy && state.pendingSave == null,
                    modifier = Modifier.testTag("chat_avatar_open"),
                ) { Text("更换会话头像") }
            }
        }
        if (state.picker == null) {
            state.notice?.let { Text(it) }
            AvatarRecovery(model, state, enabled)
        }
    }
}

@Composable
internal fun AvatarRecovery(
    model: ChatAvatarController,
    state: ChatAvatarState,
    enabled: Boolean,
) {
    if (state.loading || state.busy) {
        CircularProgressIndicator(Modifier.padding(8.dp))
    } else if (state.pendingSave != null) {
        Row {
            TextButton(
                onClick = model::retrySave,
                enabled = enabled,
                modifier = Modifier.testTag("chat_avatar_retry_save"),
            ) { Text("重试保存") }
            TextButton(onClick = model::discardPendingSave, enabled = enabled) { Text("放弃未保存选择") }
        }
    } else if (!state.loaded) {
        TextButton(onClick = model::reload) { Text("重新读取头像记录") }
    }
}
