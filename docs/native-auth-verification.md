# 双端原生账号验证

本轮已获得 Android Debug APK、iOS 模拟器应用及合成账号定向验证授权；不包含 IPA、上传或发布。这里只验证账号阶段，不代表完整 App 交付。自动 CI 仍使用 JVM / Swift 包及后端定向测试。

## 环境与范围

- Android：API 36 模拟器，应用 `com.gmaicoson.socraticmind`，独立 `uitests` 进程。
- iOS：Xcode 27.1、iOS 26.5 模拟器，SocraticMindUITests；应用用本地 ad hoc 签名，无付费账号要求。
- 后端：专用本地 FastAPI / MySQL，真实迁移、密码哈希、JWT、验证码与限流。未配置 SMTP 或模型，不向真实邮箱发送邮件。
- 读取器：`scripts.dev.auth_ui_fixture` 仅监听 127.0.0.1:8766，按平台分配随机 `example.test` 合成账号，只返回该账号对应用途的 DEV 验证码。每次 POST 分配新账号，避免重用前次代码；没有更改后端验证规则。

完整流程覆盖注册、错误验证码、验证码等待、进程重启恢复、退出后重启不恢复、错误密码、重新登录、重置密码、旧密码失效、新密码登录和再次重启恢复。iOS 另测连续输入、密码显隐、键盘下一项和清除后重新输入。

Android 使用原生无障碍输入和按钮动作，避免提示文字改变布局后坐标过期；iOS 使用 XCUITest 输入和点击。两者都通过页面操作实际服务，不通过测试后门注入登录状态。Android 的触摸命中、输入法和软键盘仍需独立设备验收，不能由无障碍动作测试推定。

## 准备独立后端

仓库根目录执行，mysqld 应为约定的 8.4 版本：

```bash
.venv/bin/python -m scripts.dev.local_backend init --directory local-data/auth-ui
.venv/bin/python -m scripts.dev.local_backend run --directory local-data/auth-ui --port 8765
```

另一个终端启动读取器：

```bash
.venv/bin/python -m scripts.dev.auth_ui_fixture --directory local-data/auth-ui
```

开始用例前确认服务 Ready、应用处于退出状态。使用专用模拟器或确认没有个人账号数据的安装；脚本不会自动清除已有应用或数据库。每个平台只运行一个用例进程，不能并发替换同平台的合成账号。重跑仍受每邮箱 60 秒、每 IP 注册 / 发码限制；等待窗口恢复或在下一次独立验证前创建新测试环境，不能在单个用例途中重置限流。

## 明确授权后构建与执行

Android 设置 JDK 21、SDK 后运行；设备序列号以 `adb devices` 为准：

```bash
android/gradlew -p android :app:assembleDebug :uitests:assembleDebug
adb -s "$ANDROID_SERIAL" install -r android/app/build/outputs/apk/debug/app-debug.apk
adb -s "$ANDROID_SERIAL" install -r android/uitests/build/outputs/apk/debug/uitests-debug.apk
adb -s "$ANDROID_SERIAL" shell am instrument -w -r \
  -e class com.gmaicoson.socraticmind.uitests.AuthFlowTest \
  com.gmaicoson.socraticmind.uitests/androidx.test.runner.AndroidJUnitRunner
```

`am instrument` 即使测试失败也可能返回 shell 成功；必须查看 `OK (1 test)` 或失败明细。截图保存在测试包 external files 的 `auth-ui` 目录，只包含合成数据，交接前仍应审查。

iOS 先生成工程，选择已安装、已启动的模拟器 ID；结果目录必须尚不存在：

```bash
.tools/xcodegen-2.46.0/xcodegen/bin/xcodegen generate --spec ios/project.yml
xcodebuild -project ios/SocraticMind.xcodeproj -scheme SocraticMind \
  -configuration Debug -destination "platform=iOS Simulator,id=$IOS_SIMULATOR_ID" \
  -derivedDataPath .tools/ios-derived -resultBundlePath .tools/ios-auth-run.xcresult \
  -parallel-testing-enabled NO -collect-test-diagnostics never \
  -only-testing:SocraticMindUITests/AuthFlowTests CODE_SIGN_IDENTITY=- test
```

此命令会构建模拟器应用和测试宿主；不会生成 IPA。保留 ad hoc 签名，让模拟器 Keychain 有应用身份；不能用禁用签名掩盖缺少钥匙串权限。查看 `xcresulttool get test-results summary` 和具体失败，不以“Testing started”或测试宿主启动成功代替通过。

## 实现取舍与待验项

iOS 26.5 的新密码输入路径曾把每个字符当作整段密码替换，并联动确认框。最终复用 `AuthTextInput`，保留 `newPassword` 内容标识，在 delegate 中应用完整替换和 UTF-16 光标位置；普通输入保留平台编辑行为，界面仍由 SwiftUI 组织。它增加了一层 UIKit 桥接，因此系统密码生成、第三方密码管理器、选择区编辑、其他 iOS 版本和真机输入法需要继续验证，不能由本轮手工输入结果推定。

Android 写请求改用零空闲连接池，避免旧连接 EOF 后不得不重放可能已提交的操作；读取继续复用连接池。新增相关 HTTP 回归，并保持禁止自动 POST 重试。写请求的建连开销是当前取舍，后续性能优化须保留幂等与失败语义。

本轮不覆盖真实邮件、真实模型、锁屏、备份恢复、卸载重装、最低系统、真机、无障碍完整审计或全部 P01 行为。中文 / emoji 密码的 XCUITest typeText 注入未得到预期字符，需要区分测试输入与平台行为后补验，未计为通过；HTTP 层的 Unicode 保留用例不能代替输入法验证。后端尚无全设备 JWT 撤销；退出只清理本机会话。实际结果以 [实施状态](execution-status.md) 为准。
