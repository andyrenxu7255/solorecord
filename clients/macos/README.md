# SoloRecord macOS 客户端

## 中文

macOS 有两种交付方式：

1. 推荐：使用 `clients/desktop` 的 Electron 工程在 macOS 构建 DMG，体验与 Windows 完全一致。
2. 备选：使用本目录的 SwiftUI + WKWebView 原生外壳，适合偏好 Apple 原生工程的运维团队。

当前 Windows 环境没有 Xcode，不能在本机生成签名 DMG。SwiftUI 外壳已预置 `SoloRecordServerURL=https://record.uino.com`；macOS 构建机上完成 Apple 签名和公证后，再上传到服务器管理页的 `macOS DMG`。

## English

macOS can be delivered in two ways:

1. Recommended: build a DMG from `clients/desktop` on macOS using Electron.
2. Alternative: use this SwiftUI + WKWebView shell.

Signed DMG packaging requires Xcode and Apple signing/notarization on macOS.
The SwiftUI shell is preconfigured for `https://record.uino.com`.
