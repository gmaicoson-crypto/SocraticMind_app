package com.gmaicoson.socraticmind.auth

import com.gmaicoson.socraticmind.network.HttpFailure
import java.io.IOException
import java.util.Locale

interface AccountRecoveryGateway {
    suspend fun sendCode(
        email: String,
        purpose: CodePurpose,
    ): String

    suspend fun resetPassword(
        email: String,
        code: String,
        newPassword: String,
    ): String
}

enum class AuthMode { LOGIN, REGISTER, RESET }

enum class AuthField { USERNAME, EMAIL, PASSWORD, CONFIRMATION, CODE }

enum class AuthOperation { SUBMIT, SEND_CODE }

/** Memory only: never put this state into saved-instance state, persistence or logs. */
data class AuthFormState(
    val mode: AuthMode = AuthMode.LOGIN,
    val username: String = "",
    val email: String = "",
    val password: String = "",
    val confirmation: String = "",
    val code: String = "",
    val busy: AuthOperation? = null,
    val cooldownSeconds: Int = 0,
    val error: String? = null,
    val notice: String? = null,
) {
    override fun toString() = "AuthFormState(mode=$mode, busy=$busy, fields=<redacted>)"
}

internal fun normalizedFormEmail(value: String) = value.trim().lowercase(Locale.ROOT)

internal fun AuthFormState.validation(codeOnly: Boolean): String? {
    val address = normalizedFormEmail(email)
    if (address.isEmpty()) return "请输入邮箱"
    if (!Regex("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$").matches(address)) return "请检查邮箱格式"
    if (codeOnly) return null
    if (mode == AuthMode.REGISTER && username.isBlank()) return "请输入用户名"
    if (password.isEmpty()) return "请输入密码"
    if (mode != AuthMode.LOGIN && password != confirmation) return "两次输入的密码不一致"
    if (mode != AuthMode.LOGIN && code.isBlank()) return "请输入验证码"
    return null
}

fun accountErrorMessage(error: Throwable): String =
    when (error) {
        is HttpFailure -> {
            error.userMessage
        }

        is SessionException -> {
            when (error.reason) {
                SessionFailure.STORAGE -> "无法完成安全存储，请重试；如注册已完成，可改用登录。"
                SessionFailure.BUSY -> "账号操作正在进行，请稍后再试。"
                SessionFailure.NOT_SIGNED_IN, SessionFailure.SUPERSEDED -> "登录状态已变化，请重新操作。"
            }
        }

        is IOException -> {
            "暂时无法连接服务，请检查网络后重试。已提交的操作可能已完成，请勿连续重复提交。"
        }

        else -> {
            "暂时无法完成操作，请稍后重试。"
        }
    }
