# SoloRecord 桌面客户端

## 中文

这是 SoloRecord 的 Electron 桌面外壳，Windows 和 macOS 共用同一套服务端 Web 体验：

- 登录：使用服务器端 LDAP/SSO 页面。
- 录音：调用浏览器录音能力，按服务器配置滚动分段上传。
- 记录：查看会议、播放录音、改角色名、编辑转写、导出。
- 状态：会话保存在 Web 安全存储中，退出账号仍在 Web 登录卡片完成。

默认连接 `https://record.uino.com`。正式打包时仍建议用环境变量显式写入服务器地址，便于后续切换环境：

```powershell
$env:SOLO_SERVER_URL="https://record.uino.com"
npm run pack
npm run portable:win
```

`portable:win` 会把服务器地址写入包内的 `server-url.txt`。员工内部分发包只允许写服务器地址，不能写任何 token/key。

本仓库不内置任何 ASR、LLM、LDAP、Hermes、ES 密钥。ASR 与大模型由服务器统一配置，桌面客户端只保存服务器地址和用户短期会话。

### Windows 构建

```powershell
cd clients\desktop
npm install
npm run dist:win
```

输出在 `clients/desktop/dist/`，典型文件名为 `SoloRecord-0.7.0-win-x64.exe`。

如果 NSIS 打包因 Windows 符号链接权限失败，可发布便携包：

```powershell
npm run pack
npm run portable:win
```

### macOS 构建

macOS DMG 必须在 macOS 构建机上执行，并完成 Apple 签名/公证：

```bash
cd clients/desktop
npm install
SOLO_SERVER_URL=https://record.uino.com npm run dist:mac
```

## English

This is the Electron desktop wrapper for SoloRecord. Windows and macOS use the
same server-hosted Web experience: login, recording, records, transcript editing,
speaker rename, exports, and downloads.

It defaults to `https://record.uino.com`. For internal distribution, build with:

```powershell
$env:SOLO_SERVER_URL="https://record.uino.com"
npm run dist:win
```

No ASR, LLM, LDAP, Hermes, ES, or external secrets are embedded in the desktop
client. ASR and LLM settings are managed by the server.
