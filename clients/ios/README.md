# SoloRecord iOS 客户端

## 中文

这是 iOS 的 WKWebView 外壳工程，用于承载服务器端 SoloRecord Web 体验。它不内置任何模型、LDAP、SSO、Hermes 或 ES 密钥，只需要配置服务器地址。

当前 Windows 开发机没有 Xcode，因此这里提供可导入 Xcode 的 Swift 源码、权限配置和构建说明；IPA 需要在 macOS 构建机上签名生成。

### 构建步骤

1. 在 macOS 安装 Xcode。
2. 用 Xcode 新建 iOS App 工程，Bundle ID 建议使用 `com.solorecord.ios`。
3. 将本目录 `SoloRecord/SoloRecord/*.swift` 和 `Info.plist` 复制到工程。
4. 将 `Info.plist` 中 `SoloRecordServerURL` 改成正式 HTTPS 地址。
5. 配置公司 Apple Developer Team、证书和 Provisioning Profile。
6. Archive 后导出 Ad Hoc 或 Enterprise IPA。
7. 在 SoloRecord Web 管理页选择 `iOS IPA` 上传发布包。

### 用户体验

iOS 端打开后即进入与 Web/Windows/macOS 相同的界面：会议、录音、App 下载和登录状态。录音依赖 WKWebView 的浏览器录音能力；如企业策略限制 Web 录音，仍可用文件补传或 Android App 采集。

## English

This is the iOS WKWebView shell for the server-hosted SoloRecord experience. It
does not embed ASR, LLM, LDAP, SSO, Hermes, ES, or external secrets.

IPA packaging requires Xcode on macOS plus company signing certificates. Update
`SoloRecordServerURL` in `Info.plist`, archive the app, export an Ad Hoc or
Enterprise IPA, then publish it from the SoloRecord Web admin page.
