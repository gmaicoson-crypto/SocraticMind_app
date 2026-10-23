package com.gmaicoson.socraticmind.account

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import com.gmaicoson.socraticmind.auth.AuthField
import com.gmaicoson.socraticmind.auth.AuthFormState
import com.gmaicoson.socraticmind.auth.AuthMode

@Composable
fun AuthFields(
    state: AuthFormState,
    edit: (AuthField, String) -> Unit,
    submit: () -> Unit,
) {
    var reveal by remember(state.mode) { mutableStateOf(false) }
    if (state.mode ==
        AuthMode.REGISTER
    ) {
        AuthInput("username", "用户名", state.username, state.busy == null, {
            edit(AuthField.USERNAME, it)
        }, hint = "2—20 个字符", submit = submit)
    }
    AuthInput("email", "邮箱", state.email, state.busy == null, {
        edit(AuthField.EMAIL, it)
    }, type = KeyboardType.Email, submit = submit)
    AuthInput(
        "password",
        if (state.mode == AuthMode.RESET) "新密码" else "密码",
        state.password,
        state.busy == null,
        { edit(AuthField.PASSWORD, it) },
        type = KeyboardType.Password,
        last = state.mode == AuthMode.LOGIN,
        hint = if (state.mode != AuthMode.LOGIN) "至少 8 位，同时包含字母和数字" else null,
        reveal = reveal,
        submit = submit,
    )
    if (state.mode != AuthMode.LOGIN) {
        AuthInput("confirmation", "确认密码", state.confirmation, state.busy == null, {
            edit(AuthField.CONFIRMATION, it)
        }, type = KeyboardType.Password, reveal = reveal, submit = submit)
        AuthInput("code", "邮箱验证码", state.code, state.busy == null, {
            edit(AuthField.CODE, it)
        }, type = KeyboardType.Number, last = true, submit = submit)
    }
    TextButton(onClick = { reveal = !reveal }, enabled = state.busy == null) { Text(if (reveal) "隐藏密码" else "显示密码") }
}

@Composable
private fun AuthInput(
    field: String,
    label: String,
    value: String,
    enabled: Boolean,
    change: (String) -> Unit,
    type: KeyboardType = KeyboardType.Text,
    last: Boolean = false,
    hint: String? = null,
    reveal: Boolean = false,
    submit: () -> Unit,
) {
    val focus = LocalFocusManager.current
    OutlinedTextField(
        value = value,
        onValueChange = change,
        enabled = enabled,
        label = { Text(label) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth().testTag("auth.$field"),
        supportingText =
            if (hint != null) {
                { Text(hint) }
            } else {
                null
            },
        visualTransformation =
            if (type == KeyboardType.Password &&
                !reveal
            ) {
                PasswordVisualTransformation()
            } else {
                VisualTransformation.None
            },
        keyboardOptions =
            KeyboardOptions(
                keyboardType = type,
                autoCorrectEnabled = false,
                imeAction = if (last) ImeAction.Done else ImeAction.Next,
            ),
        keyboardActions = KeyboardActions(onNext = { focus.moveFocus(FocusDirection.Down) }, onDone = { submit() }),
    )
}
