package com.gmaicoson.socraticmind.avatarui

import android.graphics.Bitmap
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.gmaicoson.socraticmind.chat.ChatAvatarController
import com.gmaicoson.socraticmind.chat.ChatAvatarPicker
import com.gmaicoson.socraticmind.chat.ChatAvatarResource
import com.gmaicoson.socraticmind.chat.ChatAvatarState
import com.gmaicoson.socraticmind.chat.images.AvatarImageLoader
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable
fun ChatAvatarPickerDialog(
    model: ChatAvatarController,
    state: ChatAvatarState,
    picker: ChatAvatarPicker,
    images: AvatarImageLoader<Bitmap>?,
    editable: Boolean,
) {
    val resolver = LocalContext.current.contentResolver
    val scope = rememberCoroutineScope()
    var requestedId by rememberSaveable { mutableStateOf<String?>(null) }
    var preparing by remember(picker.id) { mutableStateOf(false) }
    var error by remember(picker.id) { mutableStateOf<String?>(null) }
    val photoPicker =
        rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
            val original =
                model.state.value.picker
                    ?.takeIf { it.id == requestedId }
            requestedId = null
            if (uri != null && original != null) {
                scope.launch {
                    preparing = true
                    error = null
                    try {
                        val photo = AvatarImageCodec.prepare(resolver, uri)
                        model.upload(original, photo.bytes, photo.format)
                    } catch (failure: Exception) {
                        if (failure is CancellationException) throw failure
                        error = "无法读取这张图片。请选择 20 MB 以内、尺寸不过大的系统支持图片。"
                    } finally {
                        preparing = false
                    }
                }
            }
        }
    val enabled = editable && !state.busy && !preparing && requestedId == null && state.pendingSave == null
    val fallback = ChatAvatarResource.default(picker.target.mode)
    AlertDialog(
        onDismissRequest = { if (!state.busy && !preparing) model.dismiss() },
        title = { Text("会话头像") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                AvatarImage(AvatarPresentation(images, state.resource(picker.target), fallback), 80.dp, "当前会话头像")
                Text("选择预设，或从照片中生成静态头像。原图最大 20 MB。")
                ChatAvatarResource.presets(picker.target.mode).chunked(3).forEachIndexed { row, paths ->
                    Row {
                        paths.forEachIndexed { column, path ->
                            val resource = ChatAvatarResource(path)
                            val selected = state.resource(picker.target) == resource
                            TextButton(
                                onClick = { model.selectPreset(picker, resource) },
                                enabled = enabled,
                                modifier = Modifier.weight(1f),
                            ) {
                                Column {
                                    AvatarImage(AvatarPresentation(images, resource, fallback))
                                    Text("预设 ${row * 3 + column + 1}${if (selected) " · 已选" else ""}")
                                }
                            }
                        }
                    }
                }
                TextButton(onClick = {
                    requestedId = picker.id
                    error = null
                    try {
                        photoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                    } catch (_: Exception) {
                        requestedId = null
                        error = "系统图片选择器暂不可用，请选择预设头像。"
                    }
                }, enabled = enabled, modifier = Modifier.testTag("chat_avatar_photo")) { Text("从照片选择") }
                TextButton(onClick = { model.selectPreset(picker, null) }, enabled = enabled) { Text("恢复默认头像") }
                if (preparing) {
                    CircularProgressIndicator(Modifier.padding(8.dp))
                    Text("正在处理图片…")
                }
                error?.let { Text(it) }
                state.notice?.let { Text(it) }
                AvatarRecovery(model, state, editable && !preparing)
            }
        },
        confirmButton = {
            TextButton(onClick = model::dismiss, enabled = !state.busy && !preparing) { Text("关闭") }
        },
    )
}
