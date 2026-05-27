# SoloRecord

SoloRecord 是公司内部会议记录系统，用来通过 Android App 可靠录音，并由服务器生成和保存：

- 分角色转写文本
- 分角色会议记录
- 会议纪要
- 待办事项
- 对 Hermes Agent、OpenClaw Agent、企业微信云文档、飞书云文档等外部系统的推送

## 当前版本

这是面向公司内部使用的一体化会议记录系统，包含 Android App、服务端网关和 Web 管理/PC 端。

- Android App：统一登录跳转与回跳、滚动分段录音、本地记录、本地播放、同步到服务器、重装后恢复服务器记录、查看转写/纪要/待办、批量修改角色名。
- 服务端：登录会话、会议/音频/转写/角色/纪要/待办、ASR/LLM 配置、导出、APK 发布下载、Hermes/Webhook 转发。
- Web 端：PC 上传录音、会议查看编辑、角色重命名、导出、模型配置、任务管理、APK 发布。
- 模型密钥保存在服务端，APK 默认只需要服务器地址和短期会话 token。

## 文档入口

按读者分：

- 运维/部署/排障：[docs/human-ops/README.md](docs/human-ops/README.md)
- 开发/二次开发/API：[docs/human-dev/README.md](docs/human-dev/README.md)
- 普通使用者：[docs/user/README.md](docs/user/README.md)
- 智能体维护：[AGENTS.md](AGENTS.md)、[docs/agents/README.md](docs/agents/README.md)、[llms.txt](llms.txt)

背景资料：

- 完整 PRD：[docs/meeting-app-prd-v2.md](docs/meeting-app-prd-v2.md)
- 数据存储与 ES：[docs/data-storage-and-es.md](docs/data-storage-and-es.md)
- 本地 ASR 流水线：[docs/local-asr-pipeline.md](docs/local-asr-pipeline.md)
- 群晖 SSO 与 ASR 架构：[docs/synology-bailian-architecture.md](docs/synology-bailian-architecture.md)
- 开源调研：[docs/open-source-research.md](docs/open-source-research.md)
- 安全审计：[docs/security-audit.md](docs/security-audit.md)

## 打开方式

1. 用 Android Studio 打开本目录。
2. 等待 Android Studio 下载 Gradle 插件和 Android SDK 依赖。
3. 运行 `app` 到安卓手机或模拟器。

本机已验证 `assembleDebug` 可以通过。调试 APK 输出位置：

```text
app/build/outputs/apk/debug/app-debug.apk
```

## 一体化系统运行

服务端和 Web 管理端已经放在 `server/` 下，默认使用 SQLite 和本地文件存储，方便明天先部署跑通闭环：

```powershell
scripts\run-server.ps1
```

打开：

```text
http://127.0.0.1:8000
```

演示管理员账号可用 `admin@example.com` 登录。正式部署前请按 `docs/deployment.md` 配置 SSO、密钥、HTTPS、ASR Provider 和 APK 发布。

当前已验证：

- 服务端主流程测试通过
- API/Web smoke 测试通过
- Android `assembleDebug` 通过，包含滚动录音改动
- APK 输出：`app/build/outputs/apk/debug/app-debug.apk`

## 接口约定

转写接口、纪要接口、推送接口均使用 HTTP JSON。默认采用 OpenAI-compatible Chat Completions 风格的大模型请求；若厂商协议不同，可以在 `app/src/main/java/com/solorecord/net` 下替换对应客户端。

详细协议见：

- `docs/meeting-app-prd-v2.md`（完整 PRD，文件名沿用原版本名）
- `docs/integration-contract.md`
- `docs/synology-bailian-architecture.md`
- `docs/local-asr-pipeline.md`
- `docs/open-source-research.md`
- `docs/data-storage-and-es.md`
- `docs/roadmap.md`
- `docs/deployment.md`
- `docs/security-audit.md`

## 群晖 SSO 与百炼 Qwen ASR 结论

面向正式分发的 APK，不建议把百炼/DashScope Key、LLM Key、群晖 OIDC Client Secret 或 Hermes 工作区凭证写进 APK。APK 反编译后这些值有泄露风险。

推荐模式是：APK 只配置你自己的网关地址；网关负责群晖 SSO 登录校验、保存百炼 Key、保存大模型 Key、调用 `qwen3-asr-flash-filetrans`、生成纪要、转发到销售工作区。

`qwen3-asr-flash-filetrans` 的“离线转写”是云端长音频文件转写，不是手机本地无网转写。它通常需要先把音频放到公网可访问地址，再提交异步任务、轮询任务状态、下载临时转写结果。因此只给 APK 配 URL、Key 和 Model ID 可以做短音频原型，但不适合作为正式长会议录音方案。

如果采用自建本地 ASR，推荐 APK 仍然只负责可靠录音、滚动分段、本地播放和网络恢复后上传；本地网关/ASR 服务负责格式统一、VAD、质量检测、可选轻量降噪/去混响、可选说话人分离、ASR、纪要整理和转发。这样录音稳定性最好，也方便后续替换模型。

## 使用流程

1. 用户在 App 登录。
2. 点击“开始录音”，授权麦克风权限。
3. 点击“结束录音”，会议音频会按分段保存在本地。
4. 网络稳定后同步到服务器；同一条本地会议同步成功后会被服务器正式记录替换，避免列表重复。
5. 服务器执行 ASR、纪要整理、待办提取、外部系统转发和可选 ES/OpenSearch 索引。
6. 用户在 App 或 Web 查看转写、纪要、待办，也可以改说话人名称、下载播放服务器音频和导出文件。

## App 预配置

APK 正式分发时只建议预配置服务器地址：

```properties
SOLO_SERVER_ENDPOINT=https://record.example.com
```

ASR、LLM、SSO、Hermes、ES 等密钥都放在服务器 `server/.env` 或 Web 管理页，不写进 APK。

Android 统一登录使用系统浏览器打开：

```text
https://record.example.com/api/auth/sso/start?redirect_after=solorecord://auth/callback
```

登录完成后服务端会回跳 `solorecord://auth/callback`，APK 只保存服务端短期会话 token。

## 本地 ASR 接入

Web 管理页选择 `command` 后，可接入任何本地 ASR 脚本/二进制，只要它向 stdout 输出标准 JSON：

```text
python /opt/solorecord-asr/run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
```

详见 `docs/deployment.md` 的 Local ASR Command Adapter。
