package com.gmaicoson.socraticmind.uitests

import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import org.json.JSONObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** Runs in its own process so force-stopping the application tests actual token restoration. */
@RunWith(AndroidJUnit4::class)
class AuthFlowTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val device = UiDevice.getInstance(instrumentation)
    private val appId = "com.gmaicoson.socraticmind"

    @Test
    fun registerRestoreLogoutLoginAndReset() {
        try {
            accountFlow()
        } catch (failure: Throwable) {
            capture("failure")
            throw failure
        }
    }

    private fun accountFlow() {
        val account = AuthUiFixture.account()
        restart()
        expectSignedOut()
        capture("01-login")
        tap("auth.mode.register")
        fill("username", account.getString("username"))
        fill("email", account.getString("email"))
        fill("password", account.getString("password"))
        fill("confirmation", account.getString("password"))
        tap("auth.sendCode")
        val code = AuthUiFixture.code("register")
        val sentAt = SystemClock.elapsedRealtime()
        assertFalse(element(By.res("auth.sendCode")).isEnabled)
        fill("code", if (code == "000000") "111111" else "000000")
        tap("auth.submit")
        expectText("验证码错误")
        fill("code", code)
        tap("auth.submit")
        expectSignedIn(account)
        capture("02-registered")

        restart()
        expectSignedIn(account)
        capture("03-restored")
        logout()
        restart()
        expectSignedOut()
        fill("email", account.getString("email"))
        fill("password", "Incorrect123+")
        tap("auth.submit")
        expectText("邮箱或密码错误")
        fill("password", account.getString("password"))
        tap("auth.submit")
        expectSignedIn(account)
        logout()

        // Keep the real backend limiter active, including across app process restarts.
        Thread.sleep((61_000 - (SystemClock.elapsedRealtime() - sentAt)).coerceAtLeast(0))
        tap("auth.forgot")
        fill("email", account.getString("email"))
        fill("password", account.getString("newPassword"))
        fill("confirmation", account.getString("newPassword"))
        tap("auth.sendCode")
        fill("code", AuthUiFixture.code("reset"))
        tap("auth.submit")
        expectText("密码已更新")
        capture("04-reset")
        fill("password", account.getString("password"))
        tap("auth.submit")
        expectText("邮箱或密码错误")
        fill("password", account.getString("newPassword"))
        tap("auth.submit")
        expectSignedIn(account)
        restart()
        expectSignedIn(account)
        capture("05-new-password-restored")
        logout()
        capture("06-logged-out")
    }

    private fun element(selector: BySelector): UiObject2 {
        device.wait(Until.findObject(selector), 2_000)?.let { return it }
        for (direction in listOf(Direction.DOWN, Direction.UP)) {
            repeat(6) {
                device.findObjects(By.scrollable(true)).lastOrNull()?.scroll(direction, 0.7f)
                device.wait(Until.findObject(selector), 500)?.let { return it }
            }
        }
        error("Expected account UI element was not found: $selector")
    }

    private fun fill(
        name: String,
        value: String,
    ) {
        val target = element(By.res("auth.$name"))
        target.text = value
        device.waitForIdle()
    }

    private fun tap(identifier: String) {
        element(By.res(identifier))
        // Activate the accessible control, avoiding coordinates invalidated by error/notice layout.
        val target = checkNotNull(taggedNode(instrumentation.uiAutomation.rootInActiveWindow, identifier))
        assertTrue(target.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        device.waitForIdle()
    }

    private fun taggedNode(
        node: AccessibilityNodeInfo,
        identifier: String,
    ): AccessibilityNodeInfo? {
        if (node.viewIdResourceName == identifier) return node
        for (index in 0 until node.childCount) {
            val child = node.getChild(index) ?: continue
            taggedNode(child, identifier)?.let { return it }
        }
        return null
    }

    private fun expectText(text: String) {
        assertTrue("Expected message: $text", device.wait(Until.hasObject(By.textContains(text)), 15_000))
    }

    private fun expectSignedIn(account: JSONObject) {
        expectText("你好，${account.getString("username")}")
        expectText(account.getString("email"))
        assertFalse(device.hasObject(By.res("auth.email")))
    }

    private fun expectSignedOut() {
        assertTrue(device.wait(Until.hasObject(By.res("auth.email")), 15_000))
        assertTrue(element(By.res("auth.email")).text.isNullOrEmpty())
        assertTrue(element(By.res("auth.password")).text.isNullOrEmpty())
    }

    private fun restart() {
        device.executeShellCommand("am force-stop $appId")
        device.executeShellCommand("am start -W -n $appId/.MainActivity")
        device.waitForIdle()
    }

    private fun logout() {
        element(By.text("清理本机登录并退出")).click()
        expectSignedOut()
    }

    private fun capture(name: String) {
        val directory = File(instrumentation.context.getExternalFilesDir(null), "auth-ui")
        check(directory.isDirectory || directory.mkdirs())
        device.takeScreenshot(File(directory, "$name.png"))
        if (name == "failure") device.dumpWindowHierarchy(File(directory, "failure.xml"))
    }
}
