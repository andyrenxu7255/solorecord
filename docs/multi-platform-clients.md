# 多终端客户端交付说明

## 中文

SoloRecord V0.7 之后支持以下终端发布位：

- Android APK：原生 Java 客户端，可靠滚动录音和本地离线保护能力最完整。
- Windows EXE/ZIP：Electron 桌面客户端，承载服务器 Web 体验。
- macOS DMG：优先用 Electron 在 macOS 构建；也提供 SwiftUI + WKWebView 原生外壳源码。
- iOS IPA：SwiftUI + WKWebView 外壳源码，需要 Xcode 签名打包。
- HarmonyOS HAP：HarmonyOS Stage 模型 Web 外壳源码，需要 DevEco Studio 签名打包。

核心原则不变：终端应用不内置 ASR、LLM、LDAP、SSO、Hermes、ES 或外部系统密钥。服务器仍是权威数据源；终端只保存服务器地址、短期会话和必要缓存。

## 体验一致性

Windows、macOS、iOS、HarmonyOS 都承载同一套服务器 Web 页面，因此用户看到的主流程一致：

- 登录：LDAP 用户名密码，后续也可接统一登录跳转。
- 录音：进入“录音”页点击开始/结束；浏览器能力可用时按服务器配置分段上传。
- 文件补传：任何端都可以补传已有音频。
- 记录：查看会议、录音分段、转写、纪要、待办，修改角色名称。
- App 下载：按平台下载最新内部发布包。

Android 仍是最可靠的长会议采集端，因为它使用原生 AudioRecord、前台服务、本地 WAV 分段账本和异常恢复。桌面/iOS/Harmony 的 Web 录音依赖系统 WebView/浏览器的 `MediaRecorder` 能力，适合 PC 会议、补录和轻量移动使用；如果企业系统策略禁用了 Web 麦克风，请使用文件补传或 Android 采集。

## 构建路径

### Android

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug -PSOLO_SERVER_ENDPOINT=https://record.example.com
```

输出：

```text
app/build/outputs/apk/debug/app-debug.apk
```

### Windows

```powershell
cd clients\desktop
npm install
$env:SOLO_SERVER_URL="https://record.example.com"
npm run pack
npm run portable:win
```

输出：

```text
clients/desktop/release/SoloRecord-0.7.0-windows-x64.zip
```

如果构建机拥有 Developer Mode 或管理员权限，也可以尝试：

```powershell
npm run dist:win
```

生成 NSIS 安装 EXE。当前 Windows 机器已验证 `win-unpacked/SoloRecord.exe` 可启动；NSIS 步骤可能因 Windows 符号链接权限卡在 winCodeSign 解压。稳定交付路径是发布 portable ZIP，解压后运行其中的 `SoloRecord.exe`。

### macOS

推荐在 macOS 构建机使用 Electron：

```bash
cd clients/desktop
npm install
SOLO_SERVER_URL=https://record.example.com npm run dist:mac
```

也可以使用 `clients/macos` 的 SwiftUI + WKWebView 外壳。两种方式都需要 Apple 签名和公证。

### iOS

在 macOS + Xcode 上导入 `clients/ios` 的 Swift 文件和 `Info.plist`，把 `SoloRecordServerURL` 改成正式 HTTPS 地址，配置 Apple Developer Team 后 Archive 导出 IPA。

### HarmonyOS

在 DevEco Studio 中打开 `clients/harmony/SoloRecord`，把 `entry/src/main/ets/pages/Index.ets` 的 `DEFAULT_SERVER_URL` 改成正式 HTTPS 地址，配置公司签名后生成 HAP。

## 服务器发布

Web 管理页“发布终端应用”支持选择平台：

- Android APK
- Windows EXE
- macOS DMG
- iOS IPA
- HarmonyOS HAP

API 也支持多平台：

```text
POST /api/admin/releases
platform=windows
version_name=0.7.0
version_code=7
release_notes=SoloRecord V0.7 Windows
force_update=false
file=@SoloRecord-0.7.0-windows-x64.zip
```

查询最新版本：

```text
GET /api/web/releases/latest?platform=windows
```

下载：

```text
GET /downloads/{platform}/{version}/{file_name}
```

Android 兼容旧路径：

```text
GET /downloads/android/0.7.0/app.apk
```

## 当前工具链验证

本机已验证：

- Windows Electron 运行目录生成成功。
- `clients/desktop/dist/win-unpacked/SoloRecord.exe` 启动 smoke 通过。
- Windows portable ZIP 生成成功。

本机无法验证：

- iOS IPA、macOS DMG、HarmonyOS HAP 的签名安装包，因为当前机器没有 Xcode、DevEco Studio、hvigor 或 ohpm。

这些平台已经提供源码工程和构建说明，需在对应官方构建机上完成签名和安装验证。

## English

SoloRecord supports these client release slots after V0.7:

- Android APK: native Java client with the strongest rolling recording and offline protection.
- Windows EXE/ZIP: Electron desktop wrapper for the server-hosted Web UI.
- macOS DMG: build Electron on macOS, or use the SwiftUI + WKWebView shell.
- iOS IPA: SwiftUI + WKWebView shell, packaged with Xcode signing.
- HarmonyOS HAP: HarmonyOS Stage-model Web shell, packaged with DevEco Studio.

No client embeds ASR, LLM, LDAP, SSO, Hermes, ES, or external secrets. The server
remains authoritative; clients only store server URL, short-lived sessions, and
local cache.

The Windows Electron unpacked app and portable ZIP were generated and smoke
started on this machine. iOS, macOS, and HarmonyOS signed packages require their
official toolchains and company signing credentials.
