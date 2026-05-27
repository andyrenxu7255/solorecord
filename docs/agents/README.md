# SoloRecord 智能体维护手册

## 用途

这份文档给后续接手的 AI Agent 使用。目标是快速理解项目边界、运行方式、常见任务和不能碰的红线。

优先读取顺序：

1. `AGENTS.md`
2. `llms.txt`
3. 本文件
4. 对应任务的人类文档
5. 代码

## 当前系统状态

SoloRecord 已具备：

- Android 三页签 App。
- 登录门禁。
- 滚动分段录音。
- 本地播放。
- 服务端会议、音频、转写、纪要、待办。
- Web 管理端。
- APK 上传和下载。
- SSO 浏览器登录回跳到 Android：`solorecord://auth/callback`。
- APK 重装后从 `/api/mobile/sync` 恢复记录，并可按权限下载服务器音频分段。
- 本地 ASR 命令适配器。
- LLM 纪要适配器。
- Hermes/Webhook 转发。
- 外部 API token 调用。
- ES/OpenSearch 可选索引。
- 群晖 SSO 骨架和 demo 登录。

## 重要路径

```text
server/solorecord_server/main.py
server/solorecord_server/db.py
server/solorecord_server/auth.py
server/solorecord_server/processing.py
server/solorecord_server/repository.py
server/solorecord_server/search_index.py
server/static/app.js
server/static/index.html
app/src/main/java/com/solorecord/MainActivity.java
app/src/main/java/com/solorecord/net/RollingAudioRecorder.java
server/tests/test_api.py
```

## 运行验证

最低验证：

```powershell
scripts\run-tests.ps1
```

Android：

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug
```

Web/API smoke：

```powershell
scripts\run-server.ps1
```

然后访问：

```text
http://127.0.0.1:8000/api/health
http://127.0.0.1:8000/
```

Docker smoke fallback 见 `docs/human-ops/README.md`。

## 上下文摘要

用户目标：

- 公司内部使用，不公开分发。
- 通过群晖统一登录后才能使用。
- App 录音可靠优先。
- 每次开始/结束归为一条会议记录。
- 音频可分段，但用户看到的是一场会议。
- 可听录音、看转写、看纪要、看待办。
- 可修改说话人名称，同 speaker id 全部替换。
- 服务器保存权威数据。
- APK 重装后能从服务器恢复记录。
- 恢复后的记录能按权限下载播放服务器音频。
- 其他应用能调用数据，最好支持 ES/OpenSearch。

## 不要做

- 不要把模型 key 写进 APK。
- 不要把 `server/.env` 内容复制进文档或回答。
- 不要把 ES 当成唯一存储。
- 不要绕过 `_assert_access` 暴露会议数据。
- 不要在 Web 使用未转义的动态 HTML。
- 不要让 Android 端承担重 ASR/降噪/说话人分离。
- 不要直接复制 GPL/AGPL 项目的源代码。

## 推荐改动策略

小改动：

- 读相关文件。
- 做最小补丁。
- 跑 `scripts\run-tests.ps1`。
- 涉及 Android 跑 `assembleDebug`。

服务端接口改动：

- 改 `schemas.py` 请求模型。
- 改 `main.py` 路由。
- 改 `repository.py` 聚合输出。
- 改 `server/tests/test_api.py`。

Web 管理页改动：

- 改 `index.html` 控件。
- 改 `app.js` 读写逻辑。
- 改 `styles.css` 如需要。
- 保证密钥字段只显示“已保存”，不回显真实值。

Android 改动：

- 确认登录门禁。
- 确认录音不会因 UI 改动丢失。
- 编译 APK。

## 已知风险

- SQLite 适合初期部署，生产多用户建议迁移 PostgreSQL。
- Android token 当前在 SharedPreferences，生产建议换 EncryptedSharedPreferences/Keystore。
- Android Base64 上传用于原型，长会议建议 multipart/resumable。
- Docker BuildKit 在本地 Windows 曾因 Python 包下载慢而超时，已给出 smoke fallback；生产 Linux 构建仍按 `docker compose up -d --build solorecord`。
- PDF 中文渲染依赖系统字体，生产可启用 `INSTALL_MEDIA_TOOLS=true`。

## 关键测试用例

`server/tests/test_api.py` 覆盖完整主流程：

- 登录
- 创建会议
- 上传音频
- 处理
- 获取转写
- 说话人改名
- 导出
- 发布 APK
- 移动端同步
- 受权限保护的音频分段下载
- 外部 API

任何涉及这些流程的改动必须保持测试通过。

还要跑 HTTP smoke：

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

## 文档维护规则

新增功能时同步更新：

- 运维相关：`docs/human-ops/README.md`
- 开发相关：`docs/human-dev/README.md`
- 用户可见：`docs/user/README.md`
- 智能体接手：`AGENTS.md`、`docs/agents/README.md`、`llms.txt`

长调研和背景放到 `docs/*` 参考文档，不要塞进 `AGENTS.md`。
