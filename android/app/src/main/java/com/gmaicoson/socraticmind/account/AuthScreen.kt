package com.gmaicoson.socraticmind.account

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.gmaicoson.socraticmind.auth.AuthFormController
import com.gmaicoson.socraticmind.auth.AuthMode
import com.gmaicoson.socraticmind.auth.AuthOperation
import kotlinx.coroutines.delay

@Composable
fun AuthScreen(
    form: AuthFormController,
    expired: Boolean,
    onSubmit: () -> Unit,
    onSendCode: () -> Unit,
) {
    val state by form.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val focus = LocalFocusManager.current
    val submit = {
        focus.clearFocus()
        onSubmit()
    }
    val ticking = state.cooldownSeconds > 0
    LaunchedEffect(form, lifecycle, ticking) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            form.refreshClock()
            if (ticking) {
                while (true) {
                    delay(1_000)
                    form.refreshClock()
                }
            }
        }
    }
    Column(
        Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("SocraticMind", style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.primary)
        Text("从一个好问题开始", style = MaterialTheme.typography.titleMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            for (mode in listOf(AuthMode.LOGIN, AuthMode.REGISTER)) {
                TextButton(
                    modifier =
                        Modifier.testTag(
                            if (mode ==
                                AuthMode.LOGIN
                            ) {
                                "auth.mode.login"
                            } else {
                                "auth.mode.register"
                            },
                        ),
                    onClick = {
                        focus.clearFocus()
                        form.switchMode(mode)
                    },
                    enabled = state.busy == null,
                ) {
                    Text(if (mode == AuthMode.LOGIN) "登录" else "创建账号")
                }
            }
        }
        Text(
            when (state.mode) {
                AuthMode.LOGIN -> "欢迎回来"
                AuthMode.REGISTER -> "创建你的账号"
                AuthMode.RESET -> "找回密码"
            },
            style = MaterialTheme.typography.headlineSmall,
        )
        if (expired) Text("登录已失效，请重新登录。", color = MaterialTheme.colorScheme.error)
        AuthFields(state, form::edit, submit)
        if (state.mode != AuthMode.LOGIN) {
            TextButton(
                modifier = Modifier.testTag("auth.sendCode"),
                onClick = onSendCode,
                enabled =
                    state.busy == null && state.cooldownSeconds == 0,
            ) {
                Text(
                    when {
                        state.busy == AuthOperation.SEND_CODE -> "正在发送…"
                        state.cooldownSeconds > 0 -> "${state.cooldownSeconds} 秒后可重发"
                        else -> "发送验证码"
                    },
                )
            }
        }
        state.error?.let {
            Text(
                it,
                color = MaterialTheme.colorScheme.error,
                modifier =
                    Modifier.semantics {
                        liveRegion =
                            LiveRegionMode.Polite
                    },
            )
        }
        state.notice?.let { Text(it, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
        Button(
            onClick = submit,
            enabled = state.busy == null,
            modifier = Modifier.fillMaxWidth().testTag("auth.submit"),
        ) {
            Text(
                if (state.busy ==
                    AuthOperation.SUBMIT
                ) {
                    "正在处理…"
                } else {
                    when (state.mode) {
                        AuthMode.LOGIN -> "登录"
                        AuthMode.REGISTER -> "注册并登录"
                        AuthMode.RESET -> "更新密码"
                    }
                },
            )
        }
        if (state.mode == AuthMode.LOGIN) {
            TextButton(
                modifier = Modifier.testTag("auth.forgot"),
                onClick = { form.switchMode(AuthMode.RESET) },
                enabled =
                    state.busy == null,
            ) { Text("忘记密码？") }
        } else if (state.mode == AuthMode.RESET) {
            TextButton(onClick = { form.switchMode(AuthMode.LOGIN) }, enabled = state.busy == null) { Text("返回登录") }
        }
    }
}
