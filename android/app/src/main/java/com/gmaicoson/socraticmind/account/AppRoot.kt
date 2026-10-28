package com.gmaicoson.socraticmind.account

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.chatui.ChatLibraryScreen

@Composable
fun AppRoot(model: AppViewModel) {
    val session by model.session.collectAsStateWithLifecycle()
    val error by model.error.collectAsStateWithLifecycle()
    val avatarImages by model.avatarImages.collectAsStateWithLifecycle()
    val colors =
        if (isSystemInDarkTheme()) {
            darkColorScheme(
                primary = Color(0xFFCBBEFF),
            )
        } else {
            lightColorScheme(primary = Color(0xFF6350A2))
        }
    MaterialTheme(colorScheme = colors) {
        Surface(Modifier.fillMaxSize().semantics { testTagsAsResourceId = true }) {
            if (model.configurationError != null) {
                SessionPanel("暂时无法连接学习空间", model.configurationError)
            } else {
                when (val current = session) {
                    SessionState.Uninitialized, SessionState.Restoring -> {
                        SessionPanel("正在恢复登录", "正在验证你的账号…", loading = true)
                    }

                    SessionState.Clearing -> {
                        SessionPanel("正在退出", "正在清理本机登录信息…", loading = true)
                    }

                    is SessionState.SignedOut, SessionState.Authenticating -> {
                        model.form?.let {
                            AuthScreen(
                                it,
                                expired = (current as? SessionState.SignedOut)?.expired == true,
                                onSubmit = model::submit,
                                onSendCode = model::sendCode,
                            )
                        }
                    }

                    is SessionState.Unavailable -> {
                        SessionPanel(
                            if (current.storage) "登录信息暂不可用" else "暂时无法验证账号",
                            error ?: if (current.storage) "请解锁设备后重试；也可以清理本机登录信息。" else "请检查服务和网络，恢复后重试。",
                            action = if (current.canRetryRestore) model::restore else null,
                            clear = model::logout,
                        )
                    }

                    is SessionState.SignedIn -> {
                        key(current.revision) {
                            val history = model.history
                            val turn = model.turn
                            val actions = model.actions
                            val suggestions = model.suggestions
                            val avatars = model.avatars
                            val models = model.models
                            if (history != null && turn != null && actions != null && suggestions != null &&
                                avatars != null && models != null
                            ) {
                                ChatLibraryScreen(
                                    history,
                                    turn,
                                    actions,
                                    suggestions,
                                    models,
                                    avatars,
                                    avatarImages?.takeIf { it.account.revision == current.revision },
                                    current,
                                    model::logout,
                                    model::newConversation,
                                    model::selectConversation,
                                    model::closeConversation,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SessionPanel(
    title: String,
    message: String,
    loading: Boolean = false,
    action: (() -> Unit)? = null,
    clear: (() -> Unit)? = null,
) {
    Column(
        Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("SocraticMind", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
        Text(title, style = MaterialTheme.typography.headlineSmall)
        Text(message, style = MaterialTheme.typography.bodyLarge)
        if (loading) CircularProgressIndicator()
        action?.let { Button(onClick = it, modifier = Modifier.fillMaxWidth()) { Text("重试") } }
        clear?.let { TextButton(onClick = it) { Text("清理本机登录并退出") } }
    }
}
