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
- AudioRecord 连续 WAV 滚动分段录音。
- 相邻录音分段约 2 秒重叠，分段时长由服务器配置，默认约 5 分钟。
- 本地播放。
- 服务端会议、音频、转写、纪要、待办。
- Web 管理端。
- Web 详情页按成熟会议记录产品体验组织：状态说明、进度概览、说话人统计、纪要、可编辑待办、授权音频播放、可筛选转写时间线和任务日志。
- Android/Windows/macOS/iOS/HarmonyOS 终端应用上传和下载。
- Windows Electron 客户端、iOS WKWebView 外壳、macOS Electron/SwiftUI 外壳、HarmonyOS Web 外壳工程。
- Android 分段级断点续传：本地分段落盘，multipart 文件流上传，服务端确认后立即执行分段 ASR，并把阶段转写写回同一场会议；本地账本标记已上传，弱网重试只补传未完成分段。
- 多源同录：1-8 个录音源通过同一 `join_code` 加入同一会议。重复加入时，同一用户、同一设备名和同一录音源名称应复用原 `source_id`；同一用户显式换录音源名称时可作为另一台设备。证据键是 `(source_id, source_segment_no)`；不要只用本地分段号判断覆盖或替换。最终处理会合并重复多源片段并标记 `multi_source_merged`；设备错峰起录但来源分段相邻、时间差和文本相似度满足保守阈值时，合并片段还会标记 `multi_source_time_aligned`。冲突片段标记 `multi_source_conflict`。
- LDAP 用户名密码登录；SSO 浏览器登录回跳到 Android：`solorecord://auth/callback` 仍保留。
- APK 重装后从 `/api/mobile/sync` 恢复记录，并可按权限下载服务器音频分段。
- 待办可通过 `/api/web/meetings/{meetingId}/actions` 和 `/api/mobile/meetings/{meetingId}/actions` 更新，并进入同步、导出、外部 API 和可选 ES/OpenSearch 索引。
- 本地 ASR 命令适配器。
- LLM 纪要适配器。
- Hermes/Webhook 转发。
- 外部 API token 调用。
- ES/OpenSearch 可选索引。
- 群晖 LDAP 登录、SSO 骨架和 demo 登录。

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
server/static/styles.css
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

## 服务器运维 Agent 自动部署 Runbook

本节面向服务器运维 Agent。目标是让 Agent 在操作者提供必要 URL/key 后，自动完成部署、配置、终端应用发布和联调验收。

### 交互原则

- 只向操作者索取部署必需信息；缺省值可自动生成时，不要求人工提供。
- 密钥只写入服务器本地 `server/.env`、密钥管理系统或部署平台 secret，不写入 Git、文档、终端总结或聊天回复。
- Agent 可以回显“已配置/未配置/校验通过”，但不能回显原始 key、token、client secret、数据库密码。
- 公开 GitHub Release 终端包不包含真实服务器地址或密钥；公司内部分发包只允许内置服务器地址。
- 每次改配置后都要跑健康检查和 smoke，不允许只启动服务就结束。

### 需要向操作者收集的信息

先让操作者提供这些信息；没有的项标注“稍后配置”并使用 mock/demo 跑通：

| 类别 | 必填 | 信息 |
| --- | --- | --- |
| 服务器 | 是 | SSH 地址、登录用户、部署目录、系统类型、是否有 Docker |
| 对外访问 | 是 | `SOLO_BASE_URL`，例如 `https://record.example.com` |
| TLS/反代 | 是 | Nginx/Caddy 方案、证书来源、ACME 邮箱或已有证书路径 |
| SoloRecord 密钥 | 可自动生成 | `SOLO_SECRET_KEY`，建议 Agent 生成长随机值 |
| Demo 登录 | 是 | 是否临时开启 `SOLO_ALLOW_DEMO_LOGIN`；生产应为 `false` |
| 群晖 LDAP | 生产必填 | LDAP URL、bind DN 模板、search DN、search filter 或 searchStandard、username/email/display name 字段、emailPostfix、管理员用户名或管理员组 DN |
| 群晖 SSO/OIDC | 可稍后 | issuer、client id、client secret、redirect URI、scope、authorize/token/userinfo/JWKS URL |
| 本地 ASR | 可稍后 | provider、ASR 命令或服务地址、模型名、采样率、是否启用 diarization/denoise |
| LLM | 可稍后 | provider、endpoint、model、API key |
| Hermes/Webhook | 可稍后 | webhook URL、webhook token、目标工作区 |
| 外部 API | 可自动生成 | Hermes/CRM 拉取用 bearer token 名称和值 |
| ES/OpenSearch | 可稍后 | 是否启用、URL、index、API key 或 username/password |
| 存储与备份 | 是 | `var/` 持久化路径、备份目录、保留天数 |
| 终端应用分发 | 是 | 需要 Android、Windows、macOS、iOS、HarmonyOS 哪些平台；使用公开 Release 包，还是构建只内置服务器地址的内部分发包 |

如果操作者暂时没有群晖、ASR、LLM 或 Hermes 信息，Agent 应先部署 mock 闭环，并在最终结果中列出“待接入项”，但不能阻塞基础部署。

### 自动部署步骤

1. 检查服务器依赖：Docker、Docker Compose、磁盘空间、端口、DNS 和时间同步。
2. 获取代码：clone 或 pull `https://github.com/andyrenxu7255/solorecord.git`，checkout `v0.7` 或指定 commit。
3. 创建配置：复制 `server/.env.example` 为 `server/.env`，写入操作者提供的信息和自动生成的密钥。
4. 创建持久化目录：确认 `var/`、`var/storage`、`var/apk` 在持久磁盘上。
5. 启动服务：优先 `docker compose up -d --build solorecord`；若构建网络慢，使用 `docs/human-ops/README.md` 中的 mounted-source smoke fallback 验证。
6. 配置反向代理和 HTTPS：确保 `SOLO_BASE_URL` 和下载地址都走 HTTPS；若启用 SSO/OIDC，回调地址也必须走 HTTPS。
7. 运行健康检查：调用 `/api/health`、`/`、`/api/web/me` 匿名拒绝。
8. 跑 smoke：使用 LDAP 测试账号、demo 登录或 SSO 测试账号执行 `scripts\smoke-e2e.ps1` 对应的服务器等价流程。
9. 配置 Provider：通过 Web 管理端或 API 保存 ASR/LLM/Hermes/ES 配置；密钥字段留空表示保持不变。
10. 发布终端应用：Android 使用 `-PSOLO_SERVER_ENDPOINT=<SOLO_BASE_URL>` 构建 APK；Windows 使用 `clients/desktop` 构建 portable ZIP；macOS/iOS/HarmonyOS 在对应构建机签名出包；全部通过 `/api/admin/releases` 上传并设置 `platform`。
11. 端到端联调：测试 LDAP 登录、录音上传、弱网重试只补传未完成分段、转写/纪要、说话人改名、服务器恢复记录、服务器音频下载、外部 API 拉取。
12. 质量联调：检查 `qualityReport` 中的 `speaker_review_count`、`speaker_evidence_weak_count`、`speakerEvidence`、`summaryEvidence.supportedClaims`、`summaryEvidence.unsupportedClaims`、`actionEvidence`、`generic_owner_count`、`unsupported_action_count`、`action_evidence_coverage`、`timeline_repaired_count` 和 `scenario_counts`；真实会议不要只看纪要是否“像样”，还要看发言人、纪要和待办是否能从转写原文中找到证据。若会议纪要标题为“基于转写原文的保守整理”，表示 LLM 原始纪要证据不足，服务端已自动降级为证据优先版本。
13. 输出交付摘要：只列 URL、版本、健康状态、已启用能力、待接入项和下一步，不输出任何密钥。

### `server/.env` 写入规则

必须写入或确认：

```text
SOLO_BASE_URL=https://record.example.com
SOLO_SECRET_KEY=<generated-or-provided-secret>
SOLO_ALLOW_DEMO_LOGIN=false
SOLO_DATABASE_PATH=var/solorecord.db
SOLO_STORAGE_DIR=var/storage
SOLO_APK_DIR=var/apk
SOLO_STATIC_DIR=server/static
```

群晖 LDAP：

```text
SOLO_LDAP_ENABLED=true
SOLO_LDAP_SERVER=ldaps://ldap.example.com:636
SOLO_LDAP_BIND_DN_TEMPLATE=uid=XXX,cn=users,dc=example,dc=com
SOLO_LDAP_LOOKUP_BIND_DN=
SOLO_LDAP_LOOKUP_BIND_PASSWORD=
SOLO_LDAP_SEARCH_DN=cn=users,dc=example,dc=com
SOLO_LDAP_SEARCH_FILTER=(cn={username})
SOLO_LDAP_USERNAME_KEY=cn
SOLO_LDAP_EMAIL_KEY=mail
SOLO_LDAP_EMAIL_POSTFIX=
SOLO_LDAP_DISPLAY_NAME_KEY=displayName
SOLO_LDAP_ADMIN_USERS=
SOLO_LDAP_ADMIN_GROUP_DN=
SOLO_LDAP_TLS_VALIDATE=true
```

如果操作者提供的是 `ldapLogin` JSON，将 `server`、`baseDn`、`searchDn`、`searchStandard`、`usernameKey`、`emailKey`、`emailPostfix` 分别映射到上面的 `SOLO_LDAP_*` 项。默认不要把 `bindPassword` 写入配置；SoloRecord 使用登录界面输入的用户密码执行 bind。只有目录要求服务账号先查用户 DN 时，才把服务账号 DN 和密码写入 `SOLO_LDAP_LOOKUP_BIND_DN`、`SOLO_LDAP_LOOKUP_BIND_PASSWORD`。

群晖 SSO/OIDC（可选）：

```text
SOLO_SSO_VERIFY_MODE=oidc
SOLO_SSO_ISSUER=
SOLO_SSO_CLIENT_ID=
SOLO_SSO_CLIENT_SECRET=
SOLO_SSO_REDIRECT_URI=https://record.example.com/api/auth/sso/callback
SOLO_SSO_SCOPE=openid email
SOLO_SSO_AUTHORIZE_URL=
SOLO_SSO_TOKEN_URL=
SOLO_SSO_USERINFO_URL=
SOLO_SSO_JWKS_URL=
```

本地 ASR：

```text
SOLO_ASR_PROVIDER=command
SOLO_ASR_COMMAND=python /opt/solorecord-asr/run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
SOLO_TARGET_SAMPLE_RATE=16000
SOLO_ENABLE_DIARIZATION=true
SOLO_ENABLE_DENOISE=false
```

远程 STT / FunASR：

```text
SOLO_ASR_PROVIDER=funasr
SOLO_ASR_ENDPOINT=http://asr.example.com/v1
SOLO_ASR_API_KEY=
SOLO_ASR_MODEL=funasr-paraformer-zh
SOLO_TARGET_SAMPLE_RATE=16000
SOLO_ENABLE_DIARIZATION=true
SOLO_ENABLE_DENOISE=false
```

Agent 必须把远程 STT endpoint、key、model 只写入服务器本地 `server/.env` 或密钥系统。接口优先走 `/audio/transcriptions`，必要时回退 `/asr`；空语音结果应保留 `empty_asr` 占位转写，方便人工复核。

ASR 后语义分段：

```text
SOLO_ENABLE_SEMANTIC_SEGMENTATION=true
```

Agent 验收时必须检查：

- 如果 ASR 返回 `sentence_info`/`segments` 且带 `speaker_id`、`speaker`、`spk`、`spk_id` 或 `speakerLabel`，服务端应保留这些原生说话人字段，并写入 `asr_speaker` flag。
- 如果 ASR 只返回单段文本，或虽有多个原生 speaker 但单段很长、包含多个“某某说/某某：”标记或多个被点名人，服务端应通过 LLM 或规则拆成多个 `transcript_segments`。
- 如果 ASR 没有在“某某你先说”和“我这边/我负责”回应之间插入标点，服务端仍应把主持人点名和被点名人回应拆成两个可复核段落，并给回应段保留 `speaker_review`。
- 如果主持人点名某人负责某议题，后续段落没有“我”字但继续围绕同一议题、交付物或时间节点展开，服务端可以做 `contextual_speaker_inference`，但必须保留 `speaker_review` 和 `reason:*`，不能当成声纹确认。
- LLM 语义重分段输入和输出都应携带 `source_index`/`source_id`/`source_segment_no`。如果新增模型适配器，必须保留这些字段，避免最终转写失去原始音频分段追溯能力。
- 即使 ASR 返回多个原生 speaker，只要存在未解析的“某某负责/某某确认/某某后面看”等任务归属线索，也应进入语义后处理；不能只因为有多个 `asr_speaker` 就跳过上下文分段。
- 分段上传后应能看到带 `semantic_partial` 的阶段转写；`/finish` 后应把带 `semantic_final` 的整场上下文重分段结果写回数据库，而不是只用于纪要。
- 验证人工改名闭环：把某个 `speaker_id` 改成具体姓名后重新处理，最终时间线应保留该姓名；但旧的 `发言人 N` 泛化名称不应阻止大模型/规则识别新的真实人名。
- Web 时间线应能显示 `speaker_review`、`llm_refined`/`semantic_llm`、`semantic_rule` 对应的校对标记。
- `qualityReport.metrics.speaker_evidence_weak_count` 应反映 LLM 发言人名称是否缺少原始 ASR 证据；该值大于 0 时应优先播放对应片段。
- `qualityReport.speakerEvidence` 应包含需校对段落的 `segment_id`、`scenario_label`、`reason` 和相邻上下文；如果 Web 时间线没有显示这些信息，先修前端再做真实会议验收。
- `qualityReport.metrics.speaker_alias_conflict_count` 应反映同一 `display_name` 是否对应多个 `speaker_id`。外部知识 Agent 应按 `knowledgeGraph.nodes[].speaker_ids` 保留追溯，不要把同名多标签当成多个人。
- `knowledgeGraph.nodes` 应包含 `topic` 节点，`edges` 应包含“讨论主题”“讨论”“产生待办”“截止”等关系。外部知识 Agent 可以用 topic 连接上下文，但必须保留转写引用作为证据层。
- `qualityReport.metrics.action_evidence_coverage` 应反映待办是否有转写证据；`unsupported_action_count` 大于 0 时，前端应提示“待办缺少转写证据”，便于人工复核模型是否补写。
- `qualityReport.metrics.source_segment_coverage` 和 `qualityReport.sourceCoverage.weakSegments` 应按 `(source_id, source_segment_no)` 反映每个上传音频分段是否被最终转写覆盖。`source_segment_coverage_weak` 是知识入库阻塞项，外部知识 Agent 不得把该会议视为完整证据。`multi_source_conflict_count` 大于 0 时也应保留人工复核状态。
- 多源合并前应检查关键事实。若不同录音源在日期、数量或负责人上冲突，应保留多条 `multi_source_conflict` 证据，不得为了去重合并成单条结论。
- 多源错峰对齐只能作为去重和覆盖辅助：当 `multi_source_time_aligned` 出现时，Agent 应保留原始 `multi_source_refs:*` 追溯；若同一来源附近存在关键事实冲突，仍以 `multi_source_conflict` 和人工复核为准。
- 多源互补只能复制原始转写中存在、且与当前合并段不冲突的短语；`multi_source_complemented` 表示证据融合，不表示 LLM 生成了新事实。若附近来源存在日期、数量或负责人冲突，必须优先标记 `multi_source_conflict`。
- `qualityReport.metrics.weak_action_owner_count` 应反映待办负责人和任务之间是否缺少上下文证据；调 prompt 或规则时，不能仅因为某个人名在全文出现过，就把该人判为某项任务负责人。
- 当 `actionEvidence` 或 `weakActionOwners` 出现 `suggested_owner` 时，Web 应显示建议负责人和应用按钮；Agent 可以把它作为人工复核建议，但不得绕过用户确认直接改待办。
- 如果 LLM 输出 owner 为“我/我们/他/这边/大家”等代词，服务端应尝试用第一人称转写和任务关键词推断真实发言人；推不出必须保留 `待确认`，外部督办 Agent 不得把代词 owner 当成可发送对象。
- 如果 `processing._normalize_action_owners()` 给 task 追加 `协同：姓名`，外部督办 Agent 应保留该字段含义：owner 是主责人，协同人是配合人，不要把协同人改成新的主责人。
- `qualityReport.actionEvidence` 应逐条覆盖全部待办，并提供 `supported`、`weak_owner` 或 `unsupported` 状态和证据片段。证据片段应包含 `segment_id`、`source_segment_no`、`start_ms`、`speaker` 和 `text`，外部督办 Agent 应优先消费该字段判断是否可以自动发送提醒，并保留证据追溯链接。

LLM：

```text
SOLO_LLM_PROVIDER=openai-compatible
SOLO_LLM_ENDPOINT=
SOLO_LLM_API_KEY=
SOLO_LLM_MODEL=
```

外部系统和 ES：

```text
SOLO_HERMES_WEBHOOK_URL=
SOLO_HERMES_WEBHOOK_TOKEN=
SOLO_EXTERNAL_API_TOKENS=hermes:<long-random-token>
SOLO_ES_ENABLED=false
SOLO_ES_URL=
SOLO_ES_INDEX=solorecord_meetings
SOLO_ES_API_KEY=
SOLO_ES_USERNAME=
SOLO_ES_PASSWORD=
```

### 终端应用自动发布流程

公开 GitHub Release APK：

- 可直接下载安装。
- 不内置真实服务器地址。
- 用户首次打开后填写服务器地址。

公司内部分发 APK：

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug -PSOLO_SERVER_ENDPOINT=https://record.example.com
```

上传到服务器：

```text
POST /api/admin/releases
platform=android
version_name=0.7.0
version_code=7
release_notes=SoloRecord V0.7
force_update=false
file=@app-debug.apk
```

Agent 上传后必须检查：

```text
GET /api/web/releases/latest
GET /downloads/android/0.7.0/app.apk
```

Windows 发布：

```powershell
cd clients\desktop
npm install
$env:SOLO_SERVER_URL="<SOLO_BASE_URL>"
npm run pack
npm run portable:win
```

上传 `clients/desktop/release/SoloRecord-0.7.0-windows-x64.zip`，表单字段 `platform=windows`。如果构建机具备 Windows 符号链接权限，也可以尝试 `npm run dist:win` 生成 NSIS 安装 EXE。

macOS/iOS/HarmonyOS 发布：

- macOS：在 macOS 构建机用 `clients/desktop` 出 DMG，或用 `clients/macos` 的 SwiftUI 外壳签名出包，`platform=macos`。
- iOS：用 Xcode 导入 `clients/ios`，配置 `SoloRecordServerURL`、证书和 Provisioning Profile，导出 IPA，`platform=ios`。
- HarmonyOS：用 DevEco Studio 打开 `clients/harmony/SoloRecord`，配置 `DEFAULT_SERVER_URL` 和签名，导出 HAP，`platform=harmony`。
- 任何端都不能写入模型、LDAP、SSO、Hermes、ES 密钥。

### 联调验收清单

- Web 可打开，`/api/health` 返回 `ok`。
- 未登录访问会议列表返回 401。
- SSO 登录可回到 Web；Android 可回到 `solorecord://auth/callback`。
- 管理员可配置 ASR/LLM/Hermes/ES，密钥不回显。
- 所需终端应用已发布，下载链接可用。
- Android 登录后可录音、结束、同步。
- 录音分段默认约 5 分钟，带约 2 秒重叠；在线时每段完成后上传并返回阶段转写。
- 服务器生成转写、纪要和待办；mock 模式下也必须有占位结果。
- 说话人改名后，同 speaker id 全部替换。
- APK 重装后可从 `/api/mobile/sync` 恢复服务器记录。
- 恢复记录可按权限下载播放服务器音频。
- 外部 API 用正确 token 可拉取会议，用错误 token 返回 401。
- ES/OpenSearch 启用时，处理完成、编辑转写、改名后能索引或重建索引。
- 备份任务已配置，且 `server/.env` 没有进入 Git 或镜像。

### 故障处理顺序

1. 服务起不来：查 Docker logs、`.env` 路径、端口占用、Python 依赖。
2. Web 可开但登录失败：查 `SOLO_BASE_URL`、SSO redirect URI、反代 HTTPS Host、群晖 client secret。
3. Android 回跳失败：查 manifest scheme、`redirect_after=solorecord://auth/callback`、浏览器是否拦截。
4. 上传失败：查 token、`SOLO_BASE_URL`、反代 body size、`var/storage` 权限。
5. 弱网重复同步：确认 Android 本地 `audioSegments[].uploadStatus` 已持久化，`/segments` 返回 200 后下一次不应重复上传该分段；重复上传同一分段只替换该分段的 `source_segment_no` 转写；重复 `/finish` 应复用已有 job。
6. 转写失败：查 ASR command 是否可执行、stdout 是否合法 JSON、远程 STT endpoint/model/key、上游 HTTP 错误、`processing_jobs.error_message`。
7. 纪要失败：查 LLM endpoint/model/key；必要时回退 mock。
8. 终端应用下载失败：查 `apk_releases`、`var/apk` 文件、`platform`、反代下载路径。
9. 外部系统失败：查 `SOLO_EXTERNAL_API_TOKENS`、Hermes webhook URL/token、网络连通性。

## 上下文摘要

用户目标：

- 终端应用和生产服务面向公司内部使用，不做公开分发；源码仓库可公开，但不能包含真实密钥、运行数据、数据库、终端构建产物或客户会议音频。
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

- 不要把模型 key 写进 APK、EXE、DMG、IPA 或 HAP。
- 不要把 `server/.env` 内容复制进文档或回答。
- 不要把 ES 当成唯一存储。
- 不要绕过 `_assert_access` 暴露会议数据。
- 转写是知识平台的原始证据层。外部知识整理 Agent 只能通过 `/api/external/meetings/{meetingId}/transcript?include_history=true` 拉取，不能直接读 SQLite、`var/` 或音频文件路径。
- 外部响应里的 `knowledgeReadiness` 是入库门禁摘要。`status=hold` 时不要自动沉淀纪要或督办；`status=review_first` 时可以入库但必须保留风险标记；`status=ready` 才适合无人工介入地进入知识库。
- 非 admin 不允许删除转写段；转写重处理、分段重传或人工替换前必须保留 `transcript_segment_history`。
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
- 编译对应终端应用。

## 已知风险

- SQLite 适合初期部署，生产多用户建议迁移 PostgreSQL。
- Android token 当前在 SharedPreferences，生产建议换 EncryptedSharedPreferences/Keystore。
- Android 上传已使用 multipart 文件流和分段级断点续传；它不是单文件字节 offset 续传。若未来把分段时长调得很长，再评估更细粒度的对象存储分片上传。
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
- 发布终端应用
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

## English

### Purpose

This document is for future AI agents maintaining SoloRecord. It summarizes project boundaries, run commands, common tasks, and hard safety rules.

Recommended reading order:

1. `AGENTS.md`
2. `llms.txt`
3. This file
4. The relevant human manual
5. Code

### Current System State

SoloRecord currently includes:

- Android three-tab app.
- Login gate.
- Rolling segmented recording.
- Local playback.
- Server-side meetings, audio, transcripts, summaries, and action items.
- Web admin UI.
- Android/Windows/macOS/iOS/HarmonyOS client upload/download.
- Windows Electron client, iOS WKWebView shell, macOS Electron/SwiftUI shell, and HarmonyOS Web shell projects.
- Android segment-level upload resume: recording segments are stored locally, uploaded as multipart files, marked uploaded after server acknowledgement, and skipped on retry.
- Multi-source recording: 1-8 sources join the same meeting through `join_code`. Repeated joins should reuse the existing `source_id` when the same user, device name, and source label match; the same user may register another device by changing the source label. The evidence key is `(source_id, source_segment_no)`, not `source_segment_no` alone. Final processing merges duplicate multi-source rows with `multi_source_merged`; if devices start at different times but source-local segment numbers, start-time delta, and text similarity pass conservative checks, merged rows also carry `multi_source_time_aligned`. Divergent rows are flagged with `multi_source_conflict`.
- LDAP username/password login. Browser SSO returning to Android through `solorecord://auth/callback` remains available.
- APK reinstall recovery through `/api/mobile/sync`, including permission-protected server audio download.
- Local ASR command adapter.
- LLM summary adapter.
- Hermes/Webhook forwarding.
- External API token access.
- Optional ES/OpenSearch indexing.
- Synology LDAP login, SSO skeleton, and demo login.

### Important Paths

```text
server/solorecord_server/main.py
server/solorecord_server/db.py
server/solorecord_server/auth.py
server/solorecord_server/processing.py
server/solorecord_server/repository.py
server/solorecord_server/search_index.py
server/static/app.js
server/static/index.html
server/static/styles.css
app/src/main/java/com/solorecord/MainActivity.java
app/src/main/java/com/solorecord/net/RollingAudioRecorder.java
server/tests/test_api.py
```

### Verification

Minimum server verification:

```powershell
scripts\run-tests.ps1
```

Android:

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug
```

Web/API smoke:

```powershell
scripts\run-server.ps1
```

Then open:

```text
http://127.0.0.1:8000/api/health
http://127.0.0.1:8000/
```

Docker smoke fallback is documented in `docs/human-ops/README.md`.

### Server Operations Agent Auto-Deployment Runbook

This section is for a server operations agent. The goal is to collect required URLs/keys from the operator, then automatically deploy, configure, publish client packages, and run integration checks.

#### Interaction Rules

- Ask only for information required for deployment. Generate defaults automatically when safe.
- Store secrets only in server-local `server/.env`, a secret manager, or deployment-platform secrets. Never write them to Git, docs, summaries, or chat responses.
- It is acceptable to report "configured", "missing", or "validated"; never echo raw keys, tokens, client secrets, or database passwords.
- Public GitHub Release client packages contain no real server URL or secret. Internal company packages may embed only the server URL.
- After every config change, run health checks and smoke tests. Do not stop after merely starting containers.

#### Information To Collect From The Operator

| Category | Required | Information |
| --- | --- | --- |
| Server | Yes | SSH host, user, deploy directory, OS, Docker availability |
| Public access | Yes | `SOLO_BASE_URL`, for example `https://record.example.com` |
| TLS / reverse proxy | Yes | Nginx/Caddy choice, certificate source, ACME email or existing cert path |
| SoloRecord secret | Can generate | `SOLO_SECRET_KEY`, preferably generated by the agent |
| Demo login | Yes | Whether `SOLO_ALLOW_DEMO_LOGIN` is temporarily enabled; production should be `false` |
| Synology LDAP | Required for production | LDAP URL, bind DN template, search DN, search filter or searchStandard, username/email/display-name fields, emailPostfix, admin usernames or admin group DN |
| Synology SSO/OIDC | Can defer | issuer, client id, client secret, redirect URI, scope, authorize/token/userinfo/JWKS URLs |
| Local ASR | Can defer | provider, command or service URL, model, sample rate, diarization/denoise flags |
| LLM | Can defer | provider, endpoint, model, API key |
| Hermes/Webhook | Can defer | webhook URL, webhook token, target workspace |
| External API | Can generate | bearer token names and values for Hermes/CRM pull access |
| ES/OpenSearch | Can defer | enabled flag, URL, index, API key or username/password |
| Storage and backup | Yes | persistent `var/` path, backup directory, retention |
| Client distribution | Yes | Required platforms: Android, Windows, macOS, iOS, HarmonyOS; public Release packages or internal packages rebuilt with the server URL |

If Synology, ASR, LLM, or Hermes values are not ready, deploy the mock/demo loop first and list the missing integrations in the final handoff.

#### Automated Deployment Steps

1. Check server prerequisites: Docker, Compose, disk, ports, DNS, time sync.
2. Clone or update `https://github.com/andyrenxu7255/solorecord.git`; checkout `v0.7` or the requested commit.
3. Copy `server/.env.example` to `server/.env`; write operator-provided values and generated secrets.
4. Create persistent directories for `var/`, `var/storage`, and `var/apk`.
5. Start with `docker compose up -d --build solorecord`; if builds are slow, use the mounted-source smoke fallback in `docs/human-ops/README.md`.
6. Configure HTTPS reverse proxy and confirm `SOLO_BASE_URL` and downloads use HTTPS; if SSO/OIDC is enabled, its callback must also use HTTPS.
7. Run health checks: `/api/health`, `/`, and anonymous 401 checks.
8. Run smoke with an LDAP test account, demo login, or an SSO test account.
9. Save ASR/LLM/Hermes/ES provider settings through Web admin or API. Empty secret fields mean "keep unchanged".
10. Publish client packages. For Android, rebuild with `-PSOLO_SERVER_ENDPOINT=<SOLO_BASE_URL>`; for Windows, build the `clients/desktop` portable ZIP; for macOS/iOS/HarmonyOS, use the matching official build machine. Upload all packages through `/api/admin/releases` with `platform`.
11. Run end-to-end integration: LDAP login, recording upload, weak-network retry that sends only pending segments, transcript/summary, speaker rename, server recovery, protected audio download, external API pull.
12. Run a read-only LLM quality probe on at least one real completed meeting. Use `python -m solorecord_server.quality_probe --meeting-id <meeting_id>` for current persisted quality, and add `--run-llm` only when the configured LLM can be called safely. Confirm the output has acceptable `qualityReport.status`, candidate people, speaker review count, `speaker_evidence_weak_count`, timeline repair count, action owner quality, `unsupported_action_count`, and `action_evidence_coverage`. If a generated summary says it is a conservative transcript-grounded summary, the original LLM summary failed evidence checks and was safely downgraded. This command must not rewrite transcript rows or action items.
13. Return a handoff summary with URLs, version, health state, enabled capabilities, missing integrations, LLM quality probe result, and next actions. Do not include secrets.

#### `server/.env` Writing Rules

Required baseline:

```text
SOLO_BASE_URL=https://record.example.com
SOLO_SECRET_KEY=<generated-or-provided-secret>
SOLO_ALLOW_DEMO_LOGIN=false
SOLO_DATABASE_PATH=var/solorecord.db
SOLO_STORAGE_DIR=var/storage
SOLO_APK_DIR=var/apk
SOLO_STATIC_DIR=server/static
```

Synology LDAP:

```text
SOLO_LDAP_ENABLED=true
SOLO_LDAP_SERVER=ldaps://ldap.example.com:636
SOLO_LDAP_BIND_DN_TEMPLATE=uid=XXX,cn=users,dc=example,dc=com
SOLO_LDAP_LOOKUP_BIND_DN=
SOLO_LDAP_LOOKUP_BIND_PASSWORD=
SOLO_LDAP_SEARCH_DN=cn=users,dc=example,dc=com
SOLO_LDAP_SEARCH_FILTER=(cn={username})
SOLO_LDAP_USERNAME_KEY=cn
SOLO_LDAP_EMAIL_KEY=mail
SOLO_LDAP_EMAIL_POSTFIX=
SOLO_LDAP_DISPLAY_NAME_KEY=displayName
SOLO_LDAP_ADMIN_USERS=
SOLO_LDAP_ADMIN_GROUP_DN=
SOLO_LDAP_TLS_VALIDATE=true
```

If the operator provides a `ldapLogin` JSON object, map `server`, `baseDn`, `searchDn`, `searchStandard`, `usernameKey`, `emailKey`, and `emailPostfix` to the matching `SOLO_LDAP_*` values above. By default, do not store `bindPassword`; SoloRecord binds with the password entered by the user on the login screen. Only when the directory requires a service account lookup should the service DN and password be stored in `SOLO_LDAP_LOOKUP_BIND_DN` and `SOLO_LDAP_LOOKUP_BIND_PASSWORD`.

Synology SSO/OIDC (optional):

```text
SOLO_SSO_VERIFY_MODE=oidc
SOLO_SSO_ISSUER=
SOLO_SSO_CLIENT_ID=
SOLO_SSO_CLIENT_SECRET=
SOLO_SSO_REDIRECT_URI=https://record.example.com/api/auth/sso/callback
SOLO_SSO_SCOPE=openid email
SOLO_SSO_AUTHORIZE_URL=
SOLO_SSO_TOKEN_URL=
SOLO_SSO_USERINFO_URL=
SOLO_SSO_JWKS_URL=
```

Local ASR:

```text
SOLO_ASR_PROVIDER=command
SOLO_ASR_COMMAND=python /opt/solorecord-asr/run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
SOLO_TARGET_SAMPLE_RATE=16000
SOLO_ENABLE_DIARIZATION=true
SOLO_ENABLE_DENOISE=false
```

Remote STT / FunASR:

```text
SOLO_ASR_PROVIDER=funasr
SOLO_ASR_ENDPOINT=http://asr.example.com/v1
SOLO_ASR_API_KEY=
SOLO_ASR_MODEL=funasr-paraformer-zh
SOLO_TARGET_SAMPLE_RATE=16000
SOLO_ENABLE_DIARIZATION=true
SOLO_ENABLE_DENOISE=false
```

The agent must store remote STT endpoint, key, and model only in server-local
`server/.env` or a secret system. The adapter tries `/audio/transcriptions`
first and falls back to `/asr` when needed. Empty-speech output should remain
as an `empty_asr` placeholder transcript for human review.

Semantic segmentation after ASR:

```text
SOLO_ENABLE_SEMANTIC_SEGMENTATION=true
```

Agent acceptance checks:

- If ASR returns `sentence_info`/`segments` with `speaker_id`, `speaker`, `spk`, `spk_id`, or `speakerLabel`, the server should preserve native speaker fields and write the `asr_speaker` flag.
- If ASR returns one text segment, or native ASR speaker chunks are still long and contain multiple “name said/name:” markers or named call-outs, the server should split them into multiple `transcript_segments` through the LLM or rule fallback.
- If ASR omits punctuation between a named call-out and a first-person reply, the server should still split the host prompt from the called person's reply and keep `speaker_review` on the inferred reply.
- LLM semantic refinement input and output should carry `source_index`, `source_id`, and `source_segment_no`. New adapters must preserve these fields so final transcript rows remain traceable to source audio.
- If a host calls on someone for a topic and the next segment continues the same topic, deliverable, or deadline without saying “I”, the server may write `contextual_speaker_inference`; it must keep `speaker_review` and `reason:*`, and agents must not treat it as voiceprint confirmation.
- Partial transcripts should be visible after segment upload; `/finish` should write the full-meeting context-refined timeline back to the database, not only use it for summaries.
- The Web timeline should surface review markers derived from `speaker_review`, `llm_refined`/`semantic_llm`, and `semantic_rule`.
- `qualityReport.metrics.speaker_evidence_weak_count` should show whether LLM speaker names lack original ASR evidence. If it is above zero, play the affected segments first.
- `qualityReport.metrics.speaker_alias_conflict_count` should show whether one `display_name` maps to multiple `speaker_id` values. External knowledge agents should use `knowledgeGraph.nodes[].speaker_ids` for traceability instead of treating same-name labels as separate people.
- `knowledgeGraph.nodes` should include `topic` nodes, and `edges` should include “discussion topic”, “discussed”, “produced action”, and “due” relationships. External knowledge agents may use topics to bridge context, but transcript references remain the evidence layer.
- `qualityReport.metrics.action_evidence_coverage` should show whether action items are grounded in transcript evidence. If `unsupported_action_count` is above zero, the Web UI should warn reviewers before the action list is shared.
- `qualityReport.metrics.source_segment_coverage` and `qualityReport.sourceCoverage.weakSegments` should show whether each uploaded audio segment is covered by the final transcript, keyed by `(source_id, source_segment_no)`. `source_segment_coverage_weak` blocks knowledge ingestion. If `multi_source_conflict_count` is above zero, downstream agents should keep the meeting in human-review status.
- Before merging multi-source evidence, check critical facts. If sources disagree on dates, amounts, or owners, keep separate `multi_source_conflict` evidence rows instead of deduplicating them into one conclusion.
- Time-aligned multi-source merging is only a deduplication and coverage aid. When `multi_source_time_aligned` appears, agents should preserve the original `multi_source_refs:*` traceability; any nearby critical-fact disagreement still takes precedence as `multi_source_conflict` and requires human review.
- Multi-source complementation may only copy phrases that already exist in original transcript rows and do not conflict with the merged row. `multi_source_complemented` means evidence fusion, not LLM-created facts. Nearby date, amount, or owner disagreements must still take precedence as `multi_source_conflict`.
- If the LLM outputs a pronoun owner such as “I”, “we”, “he”, “this side”, or “everyone”, the server should infer a concrete speaker from first-person transcript evidence and task keywords when possible. If not possible, keep `待确认`; external action agents must not send reminders to pronoun owners.

LLM:

```text
SOLO_LLM_PROVIDER=openai-compatible
SOLO_LLM_ENDPOINT=
SOLO_LLM_API_KEY=
SOLO_LLM_MODEL=
```

External systems and ES:

```text
SOLO_HERMES_WEBHOOK_URL=
SOLO_HERMES_WEBHOOK_TOKEN=
SOLO_EXTERNAL_API_TOKENS=hermes:<long-random-token>
SOLO_ES_ENABLED=false
SOLO_ES_URL=
SOLO_ES_INDEX=solorecord_meetings
SOLO_ES_API_KEY=
SOLO_ES_USERNAME=
SOLO_ES_PASSWORD=
```

#### Client Publishing Flow

Public GitHub Release APK:

- Can be downloaded and installed directly.
- Contains no real server URL.
- User enters the server URL on first run.

Internal company APK:

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug -PSOLO_SERVER_ENDPOINT=https://record.example.com
```

Upload to server:

```text
POST /api/admin/releases
platform=android
version_name=0.7.0
version_code=7
release_notes=SoloRecord V0.7
force_update=false
file=@app-debug.apk
```

After upload, check:

```text
GET /api/web/releases/latest
GET /downloads/android/0.7.0/app.apk
```

Windows:

```powershell
cd clients\desktop
npm install
$env:SOLO_SERVER_URL="<SOLO_BASE_URL>"
npm run pack
npm run portable:win
```

Upload `clients/desktop/release/SoloRecord-0.7.0-windows-x64.zip` with `platform=windows`. If the build machine has Windows symlink privileges, `npm run dist:win` can generate an NSIS installer EXE.

macOS/iOS/HarmonyOS:

- macOS: build a DMG from `clients/desktop` on macOS, or sign the SwiftUI shell in `clients/macos`; upload with `platform=macos`.
- iOS: use Xcode with `clients/ios`, configure `SoloRecordServerURL`, certificates, and provisioning, export IPA, upload with `platform=ios`.
- HarmonyOS: use DevEco Studio with `clients/harmony/SoloRecord`, configure `DEFAULT_SERVER_URL` and signing, export HAP, upload with `platform=harmony`.
- No client package may contain ASR, LLM, LDAP, SSO, Hermes, ES, or external secrets.

#### Integration Acceptance Checklist

- Web opens and `/api/health` returns `ok`.
- Anonymous meeting-list access returns 401.
- SSO returns to Web; Android returns to `solorecord://auth/callback`.
- Admin can configure ASR/LLM/Hermes/ES; secrets are masked.
- Required client packages are published and downloadable.
- Android can sign in, record, stop, and sync.
- Recording segments default to about five minutes with about two seconds of overlap; when online, each completed segment uploads and returns a partial transcript.
- Server generates transcript, summary, and action items; mock mode must still produce placeholder output.
- Speaker rename updates all rows with the same speaker id.
- APK reinstall recovery works through `/api/mobile/sync`.
- Recovered records can download and play protected server audio.
- External API accepts the correct token and rejects a wrong token with 401.
- ES/OpenSearch indexes after processing/editing/rename when enabled.
- Backups are configured, and `server/.env` is not in Git or images.

#### Troubleshooting Order

1. Service does not start: inspect Docker logs, `.env` paths, ports, and Python dependency install.
2. Web opens but login fails: check `SOLO_BASE_URL`, SSO redirect URI, HTTPS Host forwarding, and Synology client secret.
3. Android callback fails: check manifest scheme, `redirect_after=solorecord://auth/callback`, and browser interception.
4. Upload fails: check token, `SOLO_BASE_URL`, reverse proxy body size, and `var/storage` permissions.
5. Weak-network retry duplicates work: confirm Android persisted `audioSegments[].uploadStatus`; after `/segments` returns 200 the next sync should skip that segment. Re-uploading the same segment should replace only transcript rows with that `source_segment_no`. Repeated `/finish` should reuse the existing job.
6. ASR fails: check ASR command execution, valid JSON stdout, remote STT endpoint/model/key, upstream HTTP errors, and `processing_jobs.error_message`.
7. Summary fails: check LLM endpoint/model/key; fall back to mock if needed.
8. Client download fails: check `apk_releases`, `var/apk` files, `platform`, and reverse proxy download path.
9. External integration fails: check `SOLO_EXTERNAL_API_TOKENS`, Hermes webhook URL/token, and network connectivity.

### User Goal Summary

The user wants an internal company system with:

- Synology/company unified login before use.
- Reliable recording as the top priority.
- One meeting record per start/end cycle.
- Segmented audio internally, but one meeting in the user experience.
- Audio playback, transcript, summary, and action items.
- Speaker-name correction by stable speaker id.
- Server-authoritative storage.
- APK reinstall recovery from server records.
- Protected server audio download for recovered records.
- External data access for other apps, preferably with optional ES/OpenSearch.

The repository can be public only if no real secrets, runtime data, databases, caches, client build artifacts, or customer meeting audio are committed. Production deployments remain internal.

### Do Not

- Do not put model keys in APK, EXE, DMG, IPA, or HAP packages.
- Do not copy `server/.env` values into docs or answers.
- Do not treat ES/OpenSearch as the only storage layer.
- Do not expose meeting data without `_assert_access`.
- Transcripts are the evidence layer for knowledge platforms. External
  knowledge agents must pull `/api/external/meetings/{meetingId}/transcript?include_history=true`
  and must not read SQLite, `var/`, or raw audio paths directly.
- Non-admin users must not delete transcript segments. Reprocessing, segment
  retry, or manual replacement must preserve prior rows in
  `transcript_segment_history`.
- Do not render unescaped dynamic HTML in the Web UI.
- Do not make Android responsible for heavy ASR, denoise, or diarization.
- Do not directly copy GPL/AGPL project source code.

### Recommended Change Strategy

Small change:

- Read the relevant files.
- Apply a focused patch.
- Run `scripts\run-tests.ps1`.
- If Android is touched, run `assembleDebug`.

Server API change:

- Update `schemas.py`.
- Update `main.py`.
- Update `repository.py` if response shape changes.
- Update `server/tests/test_api.py`.

Web admin change:

- Update `index.html`.
- Update `app.js`.
- Update `styles.css` only when needed.
- Keep secret fields masked; never echo real values.

Android change:

- Confirm login gating.
- Confirm recording cannot lose data due to UI changes.
- Build the relevant client package.

### Known Risks

- SQLite is acceptable for initial deployment; migrate to PostgreSQL for multi-user production.
- Android token currently uses SharedPreferences; use EncryptedSharedPreferences/Keystore before broader rollout.
- Android upload now uses multipart file streaming with segment-level resume. It is not byte-offset resume inside a single file; if segment duration is increased substantially, evaluate finer-grained object-storage multipart upload.
- Windows Docker BuildKit may stall on slow Python package downloads; use the documented mounted-source smoke fallback locally.
- PDF Chinese rendering depends on system fonts; production can enable `INSTALL_MEDIA_TOOLS=true`.

### Key Tests

`server/tests/test_api.py` covers:

- Login
- Meeting creation
- Audio upload
- Processing
- Transcript fetch
- Speaker rename
- Export
- APK publishing
- Mobile sync
- Protected audio segment download
- External API

Any change touching these flows must keep the test passing.

Also run HTTP smoke:

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

### Documentation Maintenance Rules

Update the related docs when adding features:

- Operations: `docs/human-ops/README.md`
- Development: `docs/human-dev/README.md`
- User-visible behavior: `docs/user/README.md`
- Agent handoff: `AGENTS.md`, `docs/agents/README.md`, `llms.txt`

Keep long research notes and background in `docs/*` reference files rather than overloading `AGENTS.md`.
