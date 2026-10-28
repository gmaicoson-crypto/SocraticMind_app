import XCTest

/// Explicit simulator-only integration test; requires the isolated backend and UI fixture.
@MainActor
final class AuthFlowTests: XCTestCase {
    private let app = XCUIApplication()

    func testRegisterAndOpenChat() async throws {
        continueAfterFailure = false
        let account = try await AuthUITestFixture.account()
        app.launch()
        if app.buttons["清理本机登录并退出"].waitForExistence(timeout: 3) {
            logout()
        }
        expectSignedOut()
        tap("auth.mode.register")
        fill("username", account.username)
        fill("email", account.email)
        fill("password", account.password)
        fill("confirmation", account.password)
        tap("auth.sendCode")
        try await fill("code", AuthUITestFixture.code("register"))
        tap("auth.submit")
        expectText("你好，\(account.username)")
        XCTAssertTrue(app.buttons["新建对话"].waitForExistence(timeout: 15))
        app.buttons["新建对话"].tap()
        let input = app.textFields["chat_input"]
        XCTAssertTrue(input.waitForExistence(timeout: 10))
        input.tap()
        input.typeText("Hello, help me understand Socratic learning.")
        XCTAssertTrue(app.buttons["chat_send"].isEnabled)
        capture("chat-ready")
    }

    func testPasswordTypingInLoginAndRegister() {
        continueAfterFailure = false
        app.launch()
        expectSignedOut()
        fill("password", "UiTyping123+")
        app.switches["显示密码"].firstMatch.tap()
        XCTAssertEqual(app.textFields["auth.password"].value as? String, "UiTyping123+")
        tap("auth.mode.register")
        fill("password", "UiTyping456+")
        field("password").typeText("\n")
        field("confirmation").typeText("UiTyping456+")
        app.switches["显示密码"].firstMatch.tap()
        XCTAssertEqual(app.textFields["auth.password"].value as? String, "UiTyping456+")
        XCTAssertEqual(app.textFields["auth.confirmation"].value as? String, "UiTyping456+")
        app.switches["显示密码"].firstMatch.tap()
        fill("password", "UiEdited789+")
        fill("confirmation", "UiEdited789+")
        app.switches["显示密码"].firstMatch.tap()
        XCTAssertEqual(app.textFields["auth.password"].value as? String, "UiEdited789+")
        XCTAssertEqual(app.textFields["auth.confirmation"].value as? String, "UiEdited789+")
    }

    func testRegisterRestoreLogoutLoginAndReset() async throws {
        continueAfterFailure = false
        let account = try await AuthUITestFixture.account()
        app.launch()
        expectSignedOut()
        capture("01-login")

        tap("auth.mode.register")
        fill("username", account.username)
        fill("email", account.email)
        fill("password", account.password)
        fill("confirmation", account.password)
        app.switches["显示密码"].firstMatch.tap()
        XCTAssertEqual(app.textFields["auth.password"].value as? String, account.password)
        XCTAssertEqual(app.textFields["auth.confirmation"].value as? String, account.password)
        app.switches["显示密码"].firstMatch.tap()
        tap("auth.sendCode")
        let code = try await AuthUITestFixture.code("register")
        let sentAt = Date()
        XCTAssertFalse(app.buttons["auth.sendCode"].isEnabled)
        fill("code", code == "000000" ? "111111" : "000000")
        tap("auth.submit")
        expectText("验证码错误")
        fill("code", code)
        tap("auth.submit")
        expectSignedIn(account)
        capture("02-registered")

        app.terminate()
        app.launch()
        expectSignedIn(account)
        capture("03-restored")
        logout()
        app.terminate()
        app.launch()
        expectSignedOut()
        fill("email", account.email)
        fill("password", "Incorrect123+")
        tap("auth.submit")
        expectText("邮箱或密码错误")
        fill("password", account.password)
        tap("auth.submit")
        expectSignedIn(account)
        logout()

        // Respect the real backend's per-email rate limit; never replace its limiter.
        let remaining = max(0, 61 - Date().timeIntervalSince(sentAt))
        try await Task.sleep(for: .seconds(remaining))
        tap("auth.forgot")
        fill("email", account.email)
        fill("password", account.newPassword)
        fill("confirmation", account.newPassword)
        tap("auth.sendCode")
        let resetCode = try await AuthUITestFixture.code("reset")
        fill("code", resetCode)
        tap("auth.submit")
        expectText("密码已更新")
        capture("04-reset")
        fill("password", account.password)
        tap("auth.submit")
        expectText("邮箱或密码错误")
        fill("password", account.newPassword)
        tap("auth.submit")
        expectSignedIn(account)
        app.terminate()
        app.launch()
        expectSignedIn(account)
        capture("05-new-password-restored")
        logout()
        capture("06-logged-out")
    }

    private func field(_ name: String) -> XCUIElement {
        let identifier = "auth.\(name)"
        // Password reveal can change the accessibility element type during an edit.
        return app.descendants(matching: .any).matching(identifier: identifier).element
    }

    private func fill(_ name: String, _ value: String) {
        let element = field(name)
        XCTAssertTrue(element.waitForExistence(timeout: 10), "Missing \(name) field")
        element.tap()
        let previous = element.value as? String ?? ""
        if !previous.isEmpty, previous != element.placeholderValue {
            element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count + 1))
        }
        element.typeText(value)
        if name != "password", name != "confirmation" {
            XCTAssertEqual(element.value as? String, value, "Input differs for \(name)")
        }
    }

    private func tap(_ identifier: String) {
        let element = app.buttons[identifier]
        XCTAssertTrue(element.waitForExistence(timeout: 10), "Missing \(identifier) button")
        for _ in 0 ..< 6 where !element.isHittable {
            app.swipeUp()
        }
        element.tap()
    }

    private func expectText(_ text: String) {
        let element = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
        XCTAssertTrue(element.waitForExistence(timeout: 15), "Missing expected message: \(text)")
    }

    private func expectSignedIn(_ account: AuthUITestCase) {
        expectText("你好，\(account.username)")
        expectText(account.email)
        XCTAssertFalse(app.textFields["auth.email"].exists)
    }

    private func expectSignedOut() {
        let email = app.textFields["auth.email"]
        XCTAssertTrue(email.waitForExistence(timeout: 15))
        XCTAssertTrue(["", "邮箱"].contains(email.value as? String ?? ""))
        let password = field("password")
        XCTAssertTrue(["", "密码"].contains(password.value as? String ?? ""))
    }

    private func logout() {
        app.buttons["清理本机登录并退出"].tap()
        expectSignedOut()
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
