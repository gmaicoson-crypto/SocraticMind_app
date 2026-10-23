package com.gmaicoson.socraticmind.auth

import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.File
import java.io.IOException

class AuthFormControllerTest {
    @Test
    fun sharedValidationNeverStartsAuthentication() =
        runBlocking {
            val cases =
                Json
                    .parseToJsonElement(
                        File(System.getProperty("socratic.contracts"), "auth-form.json").readText(),
                    ).jsonObject
                    .getValue("cases")
                    .jsonArray
            for (item in cases) {
                val fixture = fixture()
                val value = item.jsonObject
                fixture.form.switchMode(
                    AuthMode.valueOf(
                        value
                            .getValue("mode")
                            .jsonPrimitive.content
                            .uppercase(),
                    ),
                )
                value.getValue("fields").jsonObject.forEach { (field, text) ->
                    fixture.form.edit(AuthField.valueOf(field.uppercase()), text.jsonPrimitive.content)
                }
                fixture.form.submit()
                assertEquals(value.getValue("error").jsonPrimitive.content, fixture.form.state.value.error)
                assertEquals(SessionState.SignedOut(), fixture.session.state.value)
                assertNull(fixture.vault.value)
            }
        }

    @Test
    fun loginAndRegistrationUseSessionOwnerAndEraseSecrets() =
        runBlocking {
            for (mode in listOf(AuthMode.LOGIN, AuthMode.REGISTER)) {
                val fixture = fixture()
                fixture.fill(mode)
                fixture.form.submit()
                assertTrue(fixture.session.state.value is SessionState.SignedIn)
                assertEquals(grant(1).accessToken, fixture.vault.value)
                assertEquals("", fixture.form.state.value.password)
                assertEquals("", fixture.form.state.value.code)
                assertFalse(
                    fixture.form.state.value
                        .toString()
                        .contains("Test1234"),
                )
            }
        }

    @Test
    fun resetReturnsToLoginWithoutCreatingSession() =
        runBlocking {
            val fixture = fixture()
            fixture.fill(AuthMode.RESET)
            fixture.form.sendCode()
            assertEquals(listOf(CodePurpose.RESET), fixture.recovery.purposes)
            fixture.form.submit()
            assertEquals(1, fixture.recovery.resets)
            assertEquals(AuthMode.LOGIN, fixture.form.state.value.mode)
            assertEquals("密码已更新，请使用新密码登录。", fixture.form.state.value.notice)
            assertEquals("", fixture.form.state.value.password)
            assertEquals(SessionState.SignedOut(), fixture.session.state.value)
        }

    @Test
    fun cooldownSharesNormalizedEmailAcrossModesAndSurvivesNetworkFailure() =
        runBlocking {
            var now = -61_000L // nanoTime's origin is arbitrary and can be negative.
            val fixture = fixture { now }
            fixture.fill(AuthMode.REGISTER)
            fixture.recovery.sendAction = { throw IOException("offline") }
            fixture.form.sendCode()
            assertEquals(60, fixture.form.state.value.cooldownSeconds)
            fixture.form.switchMode(AuthMode.RESET)
            fixture.form.edit(AuthField.EMAIL, " LEARNER@EXAMPLE.TEST ")
            fixture.form.sendCode()
            assertEquals(1, fixture.recovery.purposes.size)
            now += 59_001
            fixture.form.refreshClock()
            assertEquals(1, fixture.form.state.value.cooldownSeconds)
            now += 999
            fixture.recovery.sendAction = { "验证码已发送" }
            fixture.form.sendCode()
            assertEquals(listOf(CodePurpose.REGISTER, CodePurpose.RESET), fixture.recovery.purposes)
        }

    @Test
    fun duplicateSubmissionAndEditsAreBlockedWhileRequestRuns() =
        runBlocking {
            val fixture = fixture()
            fixture.fill(AuthMode.RESET)
            val reply = CompletableDeferred<String>()
            fixture.recovery.resetAction = { reply.await() }
            val request = async(start = CoroutineStart.UNDISPATCHED) { fixture.form.submit() }
            fixture.form.submit()
            fixture.form.sendCode()
            fixture.form.switchMode(AuthMode.REGISTER)
            fixture.form.edit(AuthField.EMAIL, "another@example.test")
            assertEquals(1, fixture.recovery.resets)
            assertEquals("learner@example.test", fixture.form.state.value.email)
            assertEquals(AuthMode.RESET, fixture.form.state.value.mode)
            assertEquals(0, fixture.recovery.purposes.size)
            reply.complete("ok")
            request.await()
        }

    @Test
    fun clearingFormDiscardsLateRecoveryResponse() =
        runBlocking {
            val fixture = fixture()
            fixture.fill(AuthMode.REGISTER)
            val reply = CompletableDeferred<String>()
            fixture.recovery.sendAction = { reply.await() }
            val request = async(start = CoroutineStart.UNDISPATCHED) { fixture.form.sendCode() }
            fixture.form.reset()
            reply.complete("old message")
            request.await()
            assertEquals(AuthFormState(), fixture.form.state.value)
        }

    @Test
    fun cancellationReleasesBusyStateAndBackendErrorRemainsVisible() =
        runBlocking {
            val fixture = fixture()
            fixture.fill(AuthMode.RESET)
            fixture.recovery.resetAction = { CompletableDeferred<String>().await() }
            val request = async(start = CoroutineStart.UNDISPATCHED) { fixture.form.submit() }
            request.cancelAndJoin()
            assertNull(fixture.form.state.value.busy)
            assertNull(fixture.form.state.value.error)
            fixture.recovery.resetAction = { throw HttpFailure(400, null, "验证码已过期", null) }
            fixture.form.submit()
            assertEquals("验证码已过期", fixture.form.state.value.error)
            assertEquals(AuthMode.RESET, fixture.form.state.value.mode)
        }

    private suspend fun fixture(clock: () -> Long = { 1_000L }): FormFixture {
        val vault = MemoryVault()
        val session = SessionStore(FakeSessionGateway(), vault)
        session.restore()
        val recovery = FakeRecovery()
        return FormFixture(session, vault, recovery, AuthFormController(session, recovery, clock))
    }

    private class FormFixture(
        val session: SessionStore,
        val vault: MemoryVault,
        val recovery: FakeRecovery,
        val form: AuthFormController,
    ) {
        fun fill(mode: AuthMode) {
            form.switchMode(mode)
            for ((field, value) in mapOf(
                AuthField.USERNAME to "学员",
                AuthField.EMAIL to "learner@example.test",
                AuthField.PASSWORD to "Test1234",
                AuthField.CONFIRMATION to "Test1234",
                AuthField.CODE to "123456",
            )) {
                form.edit(field, value)
            }
        }
    }

    private class FakeRecovery : AccountRecoveryGateway {
        val purposes = mutableListOf<CodePurpose>()
        var resets = 0
        var sendAction: suspend () -> String = { "验证码已发送" }
        var resetAction: suspend () -> String = { "ok" }

        override suspend fun sendCode(
            email: String,
            purpose: CodePurpose,
        ): String {
            purposes += purpose
            return sendAction()
        }

        override suspend fun resetPassword(
            email: String,
            code: String,
            newPassword: String,
        ): String {
            resets++
            return resetAction()
        }
    }
}
