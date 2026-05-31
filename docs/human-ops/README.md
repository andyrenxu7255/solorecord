# SoloRecord 运维手册

## 适用读者

本手册给负责部署、维护、备份、权限和故障处理的人看。你不需要读 Android 或前端代码，也能完成服务器上线和日常运维。

## 系统组成

SoloRecord 由三部分组成：

- Android APK：员工录音、查看记录、同步到服务器。
- Windows/macOS/iOS/HarmonyOS 客户端：承载服务器 Web 体验，支持录音、补传、记录查看和下载。
- 服务端 API：登录、会议、音频、转写、纪要、待办、导出、多平台终端发布。
- Web 管理端：会议管理、模型配置、任务队列、终端应用下载/发布、外部接口配置。

服务端是权威数据源。APK 本地只保存录音和缓存；重装 APK 后，用户重新登录即可通过服务器同步记录。

## 部署路径

推荐先用单机部署跑通：

```text
Nginx/Caddy HTTPS
        |
SoloRecord FastAPI :8000
        |
SQLite + var/storage + var/apk
```

生产稳定后再扩展：

```text
Nginx/Caddy HTTPS
        |
SoloRecord API + Worker
        |
PostgreSQL + NAS/S3/Object Storage + ES/OpenSearch
        |
Local ASR/LLM + Hermes/Sales Workspace
```

## 服务器准备

最低建议：

- Linux 服务器或 Windows 服务器均可，优先 Linux。
- CPU 4 核以上，内存 8 GB 以上。
- 磁盘按会议音频量预估，建议从 500 GB 起。
- 如果本地 ASR 需要 GPU，ASR 服务单独部署到 GPU 主机。
- HTTPS 域名，用于 Web、APK 下载；仅启用浏览器 SSO/OIDC 时才需要回调域名。

必须准备：

- 群晖 LDAP 信息；如果后续改走浏览器统一登录，再准备 SSO/OIDC 应用信息。
- SoloRecord 服务域名。
- 本地 ASR 命令或服务地址。
- LLM 模型接口，可是 Ollama、OpenAI 兼容接口或公司内网模型。
- Hermes/销售工作区 Webhook 或外部拉取 token。

## 首次启动

Windows 本地：

```powershell
scripts\run-server.ps1
```

Linux：

```bash
cp server/.env.example server/.env
python3 -m venv .venv
. .venv/bin/activate
pip install -r server/requirements.txt
PYTHONPATH=server uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000
```

Docker：

```bash
cp server/.env.example server/.env
docker compose up -d --build solorecord
```

如果 Windows 本地 Docker 构建卡住，可先用挂载源码方式验证：

```powershell
docker run --rm --name solorecord-smoke -d -p 8000:8000 `
  -w /app -v "${PWD}:/app" --env-file server/.env `
  -e PYTHONPATH=/app/server `
  python:3.12.13-slim `
  sh -c "pip install --disable-pip-version-check --timeout 120 --retries 5 --no-cache-dir -r /app/server/requirements.txt && uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000"
```

启动后跑完整链路验收：

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

## 必改配置

`server/.env` 至少修改：

```text
SOLO_BASE_URL=https://record.example.com
SOLO_SECRET_KEY=换成足够长的随机字符串
SOLO_ALLOW_DEMO_LOGIN=false
SOLO_DATABASE_PATH=var/solorecord.db
SOLO_STORAGE_DIR=var/storage
SOLO_APK_DIR=var/apk
SOLO_STATIC_DIR=server/static
```

内网演示阶段可以临时保留：

```text
SOLO_ALLOW_DEMO_LOGIN=true
```

演示完成后关闭。

如果启用 Docker Compose 的 `full` profile，还要把 `server/.env.example`
里的 `POSTGRES_PASSWORD` 和 `MINIO_ROOT_PASSWORD` 换成长随机值。

## 群晖 LDAP 登录配置

当前 Android App 和 Web 默认使用 LDAP 用户名密码登录。员工只输入自己的 LDAP 用户名和密码；服务端用该凭据连接群晖 LDAP，校验成功后签发 SoloRecord 会话 token。APK 不保存 LDAP 密码，也不内置 LDAP 服务端凭据。

`server/.env` 示例：

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
SOLO_LDAP_ADMIN_USERS=admin_user_1,admin_user_2
SOLO_LDAP_TLS_VALIDATE=true
```

说明：

- `SOLO_LDAP_BIND_DN_TEMPLATE` 中的 `XXX` 或 `%s` 会替换为用户输入的用户名。
- 如果运维给的是 JSON 配置：`ldapLogin.server` 对应 `SOLO_LDAP_SERVER`，`baseDn` 对应 `SOLO_LDAP_BIND_DN_TEMPLATE`，`searchDn` 对应 `SOLO_LDAP_SEARCH_DN`，`searchStandard` 对应 `SOLO_LDAP_SEARCH_FILTER`，`usernameKey` 对应 `SOLO_LDAP_USERNAME_KEY`，`emailKey` 对应 `SOLO_LDAP_EMAIL_KEY`，`emailPostfix` 对应 `SOLO_LDAP_EMAIL_POSTFIX`。`bindPassword` 不写入服务器配置，使用用户登录时输入的密码。
- `SOLO_LDAP_SEARCH_FILTER` 可以写字段名 `cn`，也可以写完整过滤器片段，例如 `&(objectClass=user)(cn=%s)`。
- 默认模式是按 `SOLO_LDAP_BIND_DN_TEMPLATE` 组装用户 DN，并用用户输入的密码 bind。如果群晖必须先用服务账号搜索用户 DN，再用用户密码 bind，可额外配置 `SOLO_LDAP_LOOKUP_BIND_DN` 和 `SOLO_LDAP_LOOKUP_BIND_PASSWORD`；该密码只能写入服务器本地 `server/.env`。
- `SOLO_LDAP_EMAIL_POSTFIX` 可为空；如果 LDAP 没返回邮箱或只返回用户名，服务端会用该后缀补出邮箱。
- 如果群晖证书不是系统信任链，联调时可临时设 `SOLO_LDAP_TLS_VALIDATE=false`；生产应安装可信证书并改回 `true`。
- 管理员权限优先用 `SOLO_LDAP_ADMIN_USERS` 指定用户名；后续也可用 `SOLO_LDAP_ADMIN_GROUP_DN` 按 LDAP 组映射。
- 正式环境建议关闭 `SOLO_ALLOW_DEMO_LOGIN`。

## 群晖 SSO/OIDC 配置

LDAP 已能满足当前用户名密码登录需求。若后续希望改成浏览器跳转式统一登录，可继续使用本节。

推荐使用 OIDC。

需要在群晖 SSO 里注册：

- Client ID
- Client Secret
- Redirect URI：`https://record.example.com/api/auth/sso/callback`
- Scope：通常是 `openid email`

Android App 不保存群晖密钥。App 点击“登录”后会打开系统浏览器访问服务端 SSO 起始地址，并带上：

```text
redirect_after=solorecord://auth/callback
```

服务端完成群晖登录后会把短期 SoloRecord 会话 token 回跳给 App。正式环境关闭 `SOLO_ALLOW_DEMO_LOGIN` 后，手机端仍然可以通过这条统一登录链路登录。

服务端配置：

```text
SOLO_SSO_VERIFY_MODE=oidc
SOLO_SSO_ISSUER=https://sso.example.com
SOLO_SSO_CLIENT_ID=你的ClientID
SOLO_SSO_CLIENT_SECRET=你的ClientSecret
SOLO_SSO_REDIRECT_URI=https://record.example.com/api/auth/sso/callback
SOLO_SSO_SCOPE=openid email
SOLO_SSO_AUTHORIZE_URL=
SOLO_SSO_TOKEN_URL=
SOLO_SSO_USERINFO_URL=
SOLO_SSO_JWKS_URL=
```

如果群晖页面能给出完整 OIDC discovery 或 endpoint URL，优先填显式 URL。否则系统会按 Synology 风格从 `SOLO_SSO_ISSUER` 推导：

```text
/webman/sso/SSOOauth.cgi
/webman/sso/SSOAccessToken.cgi
```

## ASR 配置

默认 `mock` 模式用于跑通闭环：

```text
SOLO_ASR_PROVIDER=mock
```

接入本地 ASR 时，推荐使用命令适配器：

```text
SOLO_ASR_PROVIDER=command
SOLO_ASR_COMMAND=python /opt/solorecord-asr/run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
```

命令必须向 stdout 输出 JSON：

```json
{
  "segments": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "发言人 1",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "我们今天确认报价方案。",
      "confidence": 0.91
    }
  ]
}
```

可用占位符：

- `{audio}`：第一段音频路径。
- `{audio_json}`：全部音频路径 JSON 数组。
- `{audios}`：全部音频路径用空格拼接。
- `{meeting_id}`：会议 ID。
- `{sample_rate}`：目标采样率。
- `{diarization}`：是否启用说话人分离。
- `{denoise}`：是否启用降噪。

如果 ASR 已经部署成 OpenAI 兼容或 FunASR 兼容 HTTP 服务，可以直接配置远程 STT：

```text
SOLO_ASR_PROVIDER=funasr
SOLO_ASR_ENDPOINT=http://asr.example.com/v1
SOLO_ASR_API_KEY=
SOLO_ASR_MODEL=funasr-paraformer-zh
```

运维注意：

- `SOLO_ASR_PROVIDER` 可用 `openai-compatible`、`remote-stt` 或 `funasr`。
- Endpoint、API Key、Model 只写入服务器本地 `server/.env` 或 Web 管理页，不写入 APK。
- 服务端优先调用 `/audio/transcriptions`；如果对方返回 404，会回退尝试 `/asr`。
- 远程 STT 返回空文本时，系统会保存带 `empty_asr` 标记的占位转写，会议仍可查看、导出和人工复核。

## ASR 后语义分段与发言人推断

SoloRecord 会把说话人拆分分成三层处理：

1. 优先使用 ASR 返回的原生说话人字段，例如 `speaker_id`、`speaker`、`spk`、`spk_id`、`speakerLabel`。
2. 如果 ASR 只返回整段文本、单一发言人，或虽有多个原生 speaker 但出现“某某你先说”“某某你那个部分”“我这边负责”“某某负责/确认/后面看”等上下文线索，服务端会调用已配置的 LLM，对转写做语义重分段，并根据上下文、姓名前缀、冒号、任务归属、议题延续和指代关系推断发言人。
3. 如果 LLM 返回后仍残留明显的多人点名长段，例如“某某说/某某：/某某你先说/某某后面看”，服务端会再做一次规则细拆，并给这些段落保留 `speaker_review`。单个被点名人后紧跟“我这边/我负责/我会”等回应时，也会拆成主持人点名和被点名人回应两个段落。点名前的“先过整体节奏/先看背景”等主持人导语会保留给原始发言人，避免误归到第一个被点名人。
4. 如果 LLM 不可用，服务端会用轻量规则识别“张三说”“李四：”这类明确标记，也会对“被点名后下一段以我这边/我负责回应”、“同一 ASR 段里没有标点地连着某某你先说和我这边回应”，以及“没有我字但继续同一议题、交付物、时间节点”的场景做保守归属，至少把明显多人段拆开。

配置开关：

```text
SOLO_ENABLE_SEMANTIC_SEGMENTATION=true
```

运维注意：

- 该能力依赖 LLM Provider；LLM 未配置时不会阻塞转写，会自动回退规则分段。
- FunASR/OpenAI-compatible 请求会带上 `diarization=true`、`speaker_diarization=true`、`spk_model=cam++` 等参数；如果 ASR 服务实际返回 `sentence_info` 或 `segments` 里的说话人字段，系统会直接使用。
- 当前联调过的部分 FunASR 兼容服务只返回 `text`，不返回说话人字段；这时大模型语义分段就是主要补偿手段。即使 ASR 返回多个原始 speaker，只要文本里存在点名、承接回应或被点名议题延续，系统也会尝试做上下文归属，并在前端提示人工校对。
- 多源同录最终整理会合并不同录音源的重复证据，但如果不同来源在日期、数量或负责人等关键事实上冲突，会保留为 `multi_source_conflict`，不要直接交给知识平台自动入库；上线验收时要回听对应来源。
- Web 转写时间线会标记“需确认”“大模型分段”或“规则分段”。“需确认”代表模型推断可信度不足，建议会后人工校对。
- 每个分段上传后会先做分段级后处理并标记 `semantic_partial`；点击结束会议后，服务端会用整场上下文再整理一次最终时间线、纪要和待办，并标记 `semantic_final`。
- 语义重分段输出会保留 `source_index`/`source_segment_no`，方便从 Web 时间线、导出 JSON 或外部知识平台追溯到原始音频分段。通过上下文或任务归属推断的人名会保留 `speaker_review` 和 `reason:*`，上线验收时要把它当作“建议归属”，而不是声纹确认。
- 如果用户已经把某个 `speaker_id` 改成具体人名，最终整理会优先保留这个人工校正；但 `发言人 1/2/3` 这类泛化旧名不会阻止模型根据上下文识别新的真实人名。
- 会议详情里的“整理质量”会显示待办证据率。证据率低或出现“待办缺少转写证据”时，说明待办可能是模型补写或上下文关联不足，建议先回看转写/录音再对外发送。
- 会议详情里的“整理质量”也会显示分段覆盖率。如果出现“音频分段待核对”或 `source_segment_coverage_weak`，说明某个上传音频分段在当前转写中没有足够文本，可能是 ASR 空结果、重传缺失或 LLM 后处理丢段。上线验收时应先回听或重转写该分段，不要把该会议直接交给知识平台自动入库。
- 如果 `weak_action_owner_count` 大于 0，说明待办内容本身可能来自转写，但负责人和任务之间缺少明确上下文证据。上线验收时要重点检查这些待办，避免把督办消息发给错误的人。
- 如果待办负责人显示为“我、我们、他、这边、大家”等代词，系统会尝试用第一人称转写和任务关键词换成真实发言人；换不出来会降级为 `待确认`，仍应人工确认后再复制到 IM。
- 如果待办文本末尾出现 `协同：某人`，表示系统从转写中识别到配合/协助关系。它不会改变主责人，但复制给 IM 或同步给外部督办系统时应保留，避免遗漏配合人。
- `qualityReport.actionEvidence` 会逐条列出待办证据状态：`supported` 表示可找到转写依据，`majority` 表示多数录音源已确认但仍建议抽查，`weak_owner` 表示任务有依据但负责人证据弱，`unsupported` 表示缺转写依据，`conflict` 表示只由冲突片段支撑。外部 API 的 `actionItems` 也会直接带 `evidenceStatus`、`evidence`、`suggestedOwner`、`knowledgeSafe` 和 `requiresReview`，方便督办 Agent 不解析完整质量报告也能判断是否可自动提醒。若系统能找到更有证据的负责人，会同时给出 `suggested_owner` 和引用片段，Web 待办区会显示“建议负责人/应用建议”。证据引用带 `segment_id`、`source_id` 和 `source_segment_no`，Web 可用“定位转写”跳到对应原文。复制待办给 IM 时仍只复制待办正文。
- `qualityReport.multiSourceConflicts` 会把多源冲突从数量展开成可回听清单：每条包含来源、来源分段号、时间、发言人、冲突文本和附近其它冲突来源。Web“整理质量”区会直接显示这些条目并提供“定位转写”；知识平台或运维 Agent 做验收时应先看这个字段，确认后再决定是否入库。
- `knowledgeReadiness.reviewEvidence` 会把需要人工复核的证据集中到一个字段里，包括多源冲突、覆盖不足分段、发言人风险、纪要风险和待办风险。运维验收或知识平台联调时可以先看它快速定位问题，再回到转写原文核对。
- 如果 `speaker_evidence_weak_count` 大于 0，说明某些发言人名称没有在原始 ASR 文本或原始说话人标签中找到依据。上线验收时应优先播放这些片段，确认模型没有把议题、时间短语或误听词当成人名。
- `qualityReport.speakerEvidence` 会给出每个需校对发言人段落的推断场景、原因和相邻上下文。验收时不要只看数量，还要打开 Web 时间线检查“推断依据”是否符合真实会议语境。
- 如果 `speaker_alias_conflict_count` 大于 0，说明同一个姓名被多个 `speaker_id` 表示。Web 会提示“同名多标签”，知识图谱会合并展示同一人员节点并保留原始标签，验收时应确认是否需要在人物校对里统一。
- `knowledgeGraph` 会包含主题节点，把“人员讨论主题”“主题产生待办”“待办截止时间”串起来。主题来自转写和待办的轻量抽取，只用于辅助查阅和知识平台整理，最终事实仍以转写证据为准。
- LLM 纪要不是无条件保存。服务端会先检查纪要/分角色整理是否能被转写支撑；如果证据率过低，或多源冲突事实被写成确定结论，会自动改成“基于转写原文的保守整理”，并按更强转写证据修正明显错误的待办负责人。验收时如果看到这个标题，说明系统选择了保守兜底，而不是模型自由发挥。
- `qualityReport.summaryEvidence.supportedClaims` 会给出纪要和分角色整理中已匹配到的转写引用，并带 `status=supported|majority|conflict`。`majority` 表示多数录音源支撑但仍建议抽查，`conflict` 表示纪要只由冲突片段支撑，必须保留待确认语气并回听确认；`unsupportedClaims` 是缺证据结论。上线验收时应抽查三类内容：有依据的引用是否真的支撑结论，多源冲突结论是否写成了确定事实，缺依据的结论是否需要删除或改写。

## 多源同录验收

多源同录面向大会议室或多个参会人同时录音的场景。当前已支持共享会议编号加入同一会议；Web 录音页和文件补传页会显示服务端可加入会议候选，用户点击后自动填入编号。自动发现就近设备尚未实现，部署时不要承诺已经有局域网或 Bluetooth 近场发现。

验收步骤：

1. 用账号 A 创建会议，填写会议编号，例如 `ROOM0601`，录音源名称写“前排手机”。
2. 用账号 B 打开 Web 录音页或文件补传页，应看到该会议候选；点击候选后，会议编号输入框应自动填入 `ROOM0601`，但不会展示会议转写、纪要、音频或待办内容。
3. 用账号 B 在另一台终端填写同一个会议编号，录音源名称写“后排手机”。
4. 账号 B 用同一设备名和同一录音源名称重复加入一次，应返回同一个 `source_id`，录音源数量不应增加。
5. 两台设备都上传自己的第 1 段。服务端应生成两个 `audio_segments`，全局 `segment_no` 不同，但 `source_segment_no` 都是 `1`，`source_id` 分别不同。
6. Web 会议详情应显示多个录音源、多个录音分段，且两个来源的音频都可按权限下载/播放。
7. 结束会议后，重复拾音内容应出现 `multi_source_merged_count`；如果两个来源同一时间在日期、数量或负责人等关键事实上冲突，应出现 `multi_source_conflict_count` 和质量提示。不同设备只拾到不同人的并行发言时，应保留为普通单源证据，不应误报冲突。
8. 外部知识平台拉取 `/api/external/meetings/{meetingId}/transcript?include_history=true` 时，应能看到 `source_id`、`source_segment_no`、`qualityReport` 和 `knowledgeReadiness`。

运维排障要点：

- `max_sources` 限制为 1-8，上传接口也会检查来源上限；如果出现 409，先确认是否超过会议来源数。满员、已结束、已完成或失败的会议不会出现在可加入会议候选里。
- 重复点击加入时，同一账号、同一设备名、同一录音源名称应复用原 `source_id`；同一账号要开第二台设备时，应使用不同录音源名称。
- 多源会议中，不能只按 `source_segment_no` 判断覆盖率；应按 `(source_id, source_segment_no)` 看证据。
- Web 时间线筛选、待办/纪要证据里的“定位转写”也按 `(source_id, source_segment_no)` 定位。若两台设备都有第 1 段，应分别跳到对应录音源；如果跳错，优先检查前端 payload 是否丢了 `source_id`。
- `multi_source_conflict` 不是系统失败，而是提醒人工回听不同来源的同一时间段。
- 如果待办显示 `evidenceStatus=majority` 或“多数源确认”，说明多数录音源支撑同一主结果，但附近仍有少数冲突来源。此时 `knowledgeSafe=true`、`requiresReview=true`，外部督办或知识平台可以作为主证据使用，但应保留抽查回听提示。
- 如果待办显示 `evidenceStatus=conflict` 或“多源冲突待核对”，说明待办有转写证据但多录音源在日期、数量或负责人等关键事实上不一致。此时 `knowledgeSafe=false`、`requiresReview=true`，外部督办或知识平台不得自动发送提醒或写入确定知识。

## LLM 配置

默认 `mock` 生成占位纪要：

```text
SOLO_LLM_PROVIDER=mock
```

Ollama：

```text
SOLO_LLM_PROVIDER=ollama
SOLO_LLM_ENDPOINT=http://127.0.0.1:11434
SOLO_LLM_MODEL=qwen3
```

OpenAI 兼容接口：

```text
SOLO_LLM_PROVIDER=openai-compatible
SOLO_LLM_ENDPOINT=https://model.example.com/v1
SOLO_LLM_API_KEY=
SOLO_LLM_MODEL=qwen3
```

真实 API Key 只填在服务端 `server/.env` 或密钥管理系统里，不要写进 APK。

## 外部系统调用

Hermes 或其他内部系统可以通过外部 API 拉取记录：

```text
SOLO_EXTERNAL_API_TOKENS=hermes:换成长随机token,crm:另一个token
```

接口：

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

请求头：

```text
Authorization: Bearer 换成长随机token
```

## ES/OpenSearch

ES/OpenSearch 是可选检索层，不是唯一数据源。

配置：

```text
SOLO_ES_ENABLED=true
SOLO_ES_URL=http://127.0.0.1:9200
SOLO_ES_INDEX=solorecord_meetings
SOLO_ES_API_KEY=
SOLO_ES_USERNAME=
SOLO_ES_PASSWORD=
```

重建索引：

```text
POST /api/admin/search/reindex
```

需要管理员登录。

## 终端应用发布

管理员登录 Web 后进入“管理”页上传终端应用：

- 平台：Android APK、Windows EXE/ZIP、macOS DMG、iOS IPA、HarmonyOS HAP
- 版本名：例如 `0.7.0`
- 版本号：整数，递增
- 更新说明
- 是否强制更新
- 发布包文件

APK 有两种构建方式：

1. 公开 GitHub Release 附件：不内置真实服务器地址和任何密钥，首次打开后在“登录状态”页填写服务器地址，适合初装、联调和公开共享。
2. 公司内部分发 APK：构建时只内置服务器地址，不内置 token/key。

内部分发构建示例：

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug -PSOLO_SERVER_ENDPOINT=https://record.example.com
```

输出文件：

```text
app/build/outputs/apk/debug/app-debug.apk
```

用户在 Web 的“App 下载”页下载。App 的登录状态页也会提示从 Web 下载最新 APK。

Windows 客户端构建：

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

Windows ZIP 解压后运行其中的 `SoloRecord.exe`。如果构建机具备 electron-builder 所需权限，也可尝试 `npm run dist:win` 生成 NSIS 安装 EXE。
`portable:win` 会把 `SOLO_SERVER_URL` 写入 `server-url.txt`，只允许写服务器地址，不能写 token/key。

macOS 可在 macOS 构建机用 `clients/desktop` 生成 DMG，也可使用 `clients/macos` 的 SwiftUI 外壳。iOS 使用 `clients/ios` 的 WKWebView 外壳并由 Xcode 导出 IPA。HarmonyOS 使用 DevEco Studio 打开 `clients/harmony/SoloRecord` 并导出 HAP。详见 `docs/multi-platform-clients.md`。

App 重装后，本机缓存会清空，但服务器记录不丢失。用户重新登录后可在“录音”或“记录”页点击“从服务器恢复记录”。恢复后的记录带服务器音频下载地址；播放时会按用户权限下载音频分段再播放。

弱网同步说明：

- Android 先把录音连续采集为本机 WAV 滚动分段，再同步服务器。
- 分段时长由 Web 管理页/服务端配置控制，默认约 5 分钟；相邻分段保留约 2 秒重叠，避免切段边界丢词。
- 上传走 `POST /api/mobile/meetings/{meetingId}/segments` multipart 文件流，不再依赖整段 Base64 JSON。
- 每个分段上传成功后，服务端会立即执行该段 ASR，并把阶段转写写入同一个会议记录；用户不需要等整场结束才看到转写。
- 客户端本地保存分段上传账本；服务端确认某分段后，本地立刻标记为“已上传”。
- 下次同步会跳过已上传分段，只补传未完成分段。
- 这是分段级断点续传，不是单个文件的字节 offset 续传。弱网失败时最多重传当前未确认分段。
- `/finish` 可以重复调用；如果会议已有排队、运行中或已完成的处理任务，服务端会复用已有 job，避免手机弱网重试造成重复 ASR/LLM 消耗。
- 如果所有分段已经完成在线阶段转写，结束会议时服务端会复用这些转写生成完整纪要和待办，不再重复跑整场 ASR。

## 数据目录

默认目录：

```text
var/solorecord.db
var/storage/
var/apk/
```

必须备份：

- `var/solorecord.db`
- `var/storage/`
- `var/apk/`
- `server/.env`

不要把 `server/.env` 发给外部人员或放进镜像。

## 备份建议

每日备份：

- SQLite 数据库文件。
- 音频和导出文件。
- 终端应用发布文件。

备份前建议暂停写入或使用数据库一致性备份。生产长期运行建议迁移 PostgreSQL。

## 健康检查

服务健康：

```text
GET /api/health
```

返回：

```json
{"status":"ok","app":"SoloRecord"}
```

Web 首页：

```text
GET /
GET /styles.css
GET /app.js
```

## 常见故障

### 登录跳转失败

检查：

- `SOLO_BASE_URL`
- `SOLO_SSO_REDIRECT_URI`
- 群晖 SSO 应用里的回调地址
- Nginx/Caddy 是否正确转发 HTTPS Host

### App 无法同步

检查：

- App 登录状态页里的服务器地址。
- 服务器是否能访问。
- Token 是否过期。
- `GET /api/mobile/sync` 是否返回数据。

### 转写一直失败

检查：

- `SOLO_ASR_PROVIDER`
- `SOLO_ASR_COMMAND`
- `SOLO_ASR_ENDPOINT`
- `SOLO_ASR_MODEL`
- ASR 命令在服务器上是否可执行。
- ASR stdout 是否是合法 JSON。
- `processing_jobs.error_message`

### 纪要为空或占位

检查：

- `SOLO_LLM_PROVIDER`
- `SOLO_LLM_ENDPOINT`
- `SOLO_LLM_MODEL`
- `SOLO_LLM_API_KEY`

如果 LLM 未配置，系统会回退 mock 纪要。

### PDF 中文显示异常

生产镜像构建时安装 CJK 字体：

```bash
docker compose build --build-arg INSTALL_MEDIA_TOOLS=true solorecord
```

### Docker 构建卡住

本地 Windows 可先用挂载源码方式 smoke。生产服务器建议使用 Linux Docker 构建。

## 上线前检查清单

- `SOLO_SECRET_KEY` 已更换。
- `SOLO_ALLOW_DEMO_LOGIN=false`。
- HTTPS 已启用。
- SSO 回调已验证。
- ASR 命令或服务已验证。
- LLM 配置已验证。
- `var/` 已挂到持久磁盘。
- 备份任务已配置。
- 外部 API token 已换成长随机值。
- APK 已上传并可下载。
- APK 已确认只内置服务器地址，不包含 ASR/LLM/SSO/Hermes/ES token 或 key。
- 测试用户完成统一登录、录音、上传、转写、改名、导出、从服务器恢复记录、下载播放服务器音频。
- 至少选一条真实会议跑只读大模型质量探测：

```bash
docker compose exec -T solorecord python -m solorecord_server.quality_probe --meeting-id <meeting_id>
docker compose exec -T solorecord python -m solorecord_server.quality_probe --meeting-id <meeting_id> --postprocess
docker compose exec -T solorecord python -m solorecord_server.quality_probe --meeting-id <meeting_id> --run-llm
```

第一条只读当前持久化结果；`--postprocess` 只跑服务器本地后处理模拟；`--run-llm` 会调用已配置的大模型做模拟重分段和纪要探测。三种模式都不会写回数据库。上线前重点看 `qualityReport.status`、候选人名、`speaker_review_count`、`timeline_repaired_count`、`generic_owner_count` 和待办负责人是否可接受；如果使用 `--postprocess` 或 `--run-llm`，还要看 `delta.improved_metrics`、`delta.regressed_metrics`、`delta.speaker_names_added` 和 `delta.suggested_owner_changes`，确认混合段减少、发言人更完整、待办负责人建议更接近真实上下文。
- `scripts\smoke-e2e.ps1` 已通过。
- `pip-audit -r server/requirements.txt` 无已知漏洞。

## English

### Audience

This manual is for the people who deploy, operate, back up, secure, and troubleshoot SoloRecord. You do not need to read the Android or Web source code to bring the system online.

### System Components

SoloRecord has these main parts:

- Android APK: employee recording, local records, playback, and server sync.
- Windows/macOS/iOS/HarmonyOS clients: server-hosted Web experience with recording, upload, record review, and downloads.
- Server API: login, meetings, audio, transcripts, summaries, action items, exports, multi-platform client publishing, and external integrations.
- Web admin / PC UI: meeting management, provider configuration, jobs, client download/publishing, and external API configuration.

The server is the authoritative data source. The APK keeps local audio and cache only. After reinstalling the APK, users can sign in again and recover server records.

### Recommended Deployment Shape

Start with a single-machine deployment:

```text
Nginx/Caddy HTTPS
        |
SoloRecord FastAPI :8000
        |
SQLite + var/storage + var/apk
```

For production growth, move toward:

```text
Nginx/Caddy HTTPS
        |
SoloRecord API + Worker
        |
PostgreSQL + NAS/S3/Object Storage + ES/OpenSearch
        |
Local ASR/LLM + Hermes/Sales Workspace
```

### Server Preparation

Minimum recommendation:

- Linux or Windows server; Linux is preferred.
- 4+ CPU cores and 8 GB+ memory.
- Disk capacity sized for meeting audio; start from 500 GB if unsure.
- A separate GPU host if the local ASR runtime needs GPU.
- HTTPS domain for Web and APK download; callback support is only required if browser SSO/OIDC is enabled.

Prepare:

- Synology LDAP information. Prepare Synology SSO/OIDC app information only if browser-based unified login is enabled later.
- SoloRecord service domain.
- Local ASR command or service endpoint.
- LLM endpoint, such as Ollama, OpenAI-compatible API, or internal model.
- Hermes/sales workspace webhook or external pull token.

### First Start

Windows local:

```powershell
scripts\run-server.ps1
```

Linux:

```bash
cp server/.env.example server/.env
python3 -m venv .venv
. .venv/bin/activate
pip install -r server/requirements.txt
PYTHONPATH=server uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000
```

Docker:

```bash
cp server/.env.example server/.env
docker compose up -d --build solorecord
```

If a Windows Docker build stalls, use the mounted-source smoke path:

```powershell
docker run --rm --name solorecord-smoke -d -p 8000:8000 `
  -w /app -v "${PWD}:/app" --env-file server/.env `
  -e PYTHONPATH=/app/server `
  python:3.12.13-slim `
  sh -c "pip install --disable-pip-version-check --timeout 120 --retries 5 --no-cache-dir -r /app/server/requirements.txt && uvicorn solorecord_server.main:app --host 0.0.0.0 --port 8000"
```

Run the end-to-end smoke after startup:

```powershell
scripts\smoke-e2e.ps1 -BaseUrl http://127.0.0.1:8000 -ExternalToken test-token
```

### Required Configuration Changes

At minimum, edit `server/.env`:

```text
SOLO_BASE_URL=https://record.example.com
SOLO_SECRET_KEY=replace-with-a-long-random-string
SOLO_ALLOW_DEMO_LOGIN=false
SOLO_DATABASE_PATH=var/solorecord.db
SOLO_STORAGE_DIR=var/storage
SOLO_APK_DIR=var/apk
SOLO_STATIC_DIR=server/static
```

Demo login can stay enabled only during internal validation:

```text
SOLO_ALLOW_DEMO_LOGIN=true
```

Disable it before production use. If the optional Docker Compose `full` profile is enabled, replace `POSTGRES_PASSWORD` and `MINIO_ROOT_PASSWORD` with long random values.

### Synology LDAP Login

The current Android and Web login flow uses LDAP username/password login. Users enter their own LDAP username and password; the server binds to Synology LDAP with that credential, then issues a SoloRecord session token. The APK does not store LDAP passwords or LDAP service credentials.

Example `server/.env`:

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
SOLO_LDAP_ADMIN_USERS=admin_user_1,admin_user_2
SOLO_LDAP_TLS_VALIDATE=true
```

Notes:

- `XXX` or `%s` in `SOLO_LDAP_BIND_DN_TEMPLATE` is replaced by the username.
- If operations provides a JSON config, map `ldapLogin.server` to `SOLO_LDAP_SERVER`, `baseDn` to `SOLO_LDAP_BIND_DN_TEMPLATE`, `searchDn` to `SOLO_LDAP_SEARCH_DN`, `searchStandard` to `SOLO_LDAP_SEARCH_FILTER`, `usernameKey` to `SOLO_LDAP_USERNAME_KEY`, `emailKey` to `SOLO_LDAP_EMAIL_KEY`, and `emailPostfix` to `SOLO_LDAP_EMAIL_POSTFIX`. Do not store `bindPassword`; SoloRecord uses the password entered by the user at login.
- `SOLO_LDAP_SEARCH_FILTER` can be a field name such as `cn`, or a full filter fragment such as `&(objectClass=user)(cn=%s)`.
- The default mode builds a user DN from `SOLO_LDAP_BIND_DN_TEMPLATE` and binds with the user's password. If Synology requires a service account to search the real user DN first, also configure `SOLO_LDAP_LOOKUP_BIND_DN` and `SOLO_LDAP_LOOKUP_BIND_PASSWORD`; keep that password only in server-local `server/.env`.
- `SOLO_LDAP_EMAIL_POSTFIX` can be empty. If LDAP does not return an email or returns only a local name, the server appends this postfix.
- If Synology uses an internal certificate during validation, temporarily set `SOLO_LDAP_TLS_VALIDATE=false`; production should trust the certificate chain and keep validation enabled.
- Use `SOLO_LDAP_ADMIN_USERS` for the first admin accounts, or `SOLO_LDAP_ADMIN_GROUP_DN` for group-based admin mapping.
- Disable `SOLO_ALLOW_DEMO_LOGIN` for formal use.

### Synology SSO/OIDC

LDAP covers the current username/password flow. Use this optional section if the company later wants browser-based unified login.

Register these in Synology SSO/OIDC:

- Client ID
- Client Secret
- Redirect URI: `https://record.example.com/api/auth/sso/callback`
- Scope, usually `openid email`

The Android APK never stores the Synology secret. The APK opens the server SSO start URL with:

```text
redirect_after=solorecord://auth/callback
```

The server completes SSO and returns a short-lived SoloRecord session token to the APK.

Server configuration:

```text
SOLO_SSO_VERIFY_MODE=oidc
SOLO_SSO_ISSUER=https://sso.example.com
SOLO_SSO_CLIENT_ID=your-client-id
SOLO_SSO_CLIENT_SECRET=your-client-secret
SOLO_SSO_REDIRECT_URI=https://record.example.com/api/auth/sso/callback
SOLO_SSO_SCOPE=openid email
SOLO_SSO_AUTHORIZE_URL=
SOLO_SSO_TOKEN_URL=
SOLO_SSO_USERINFO_URL=
SOLO_SSO_JWKS_URL=
```

Prefer explicit OIDC endpoint URLs when Synology provides them. Otherwise, the server can infer Synology-style `/webman/sso/SSOOauth.cgi` and `/webman/sso/SSOAccessToken.cgi` endpoints from `SOLO_SSO_ISSUER`.

### ASR Provider

Default mock mode keeps the full system runnable:

```text
SOLO_ASR_PROVIDER=mock
```

For a local ASR runtime, use the command adapter:

```text
SOLO_ASR_PROVIDER=command
SOLO_ASR_COMMAND=python /opt/solorecord-asr/run_asr.py --audios-json {audio_json} --sample-rate {sample_rate}
```

The command must print JSON to stdout:

```json
{
  "segments": [
    {
      "speaker_id": "SPEAKER_01",
      "display_name": "Speaker 1",
      "start_ms": 0,
      "end_ms": 5200,
      "text": "Let's confirm the quote today.",
      "confidence": 0.91
    }
  ]
}
```

Supported placeholders include `{audio}`, `{audio_json}`, `{audios}`, `{meeting_id}`, `{sample_rate}`, `{diarization}`, and `{denoise}`.

If ASR is already exposed as an OpenAI-compatible or FunASR-compatible HTTP
service, configure remote STT:

```text
SOLO_ASR_PROVIDER=funasr
SOLO_ASR_ENDPOINT=http://asr.example.com/v1
SOLO_ASR_API_KEY=
SOLO_ASR_MODEL=funasr-paraformer-zh
```

Operations notes:

- `SOLO_ASR_PROVIDER` can be `openai-compatible`, `remote-stt`, or `funasr`.
- Endpoint, API key, and model belong only in server-local `server/.env` or Web admin configuration, never in the APK.
- The server calls `/audio/transcriptions` first; if the service returns 404, it falls back to `/asr`.
- Empty remote STT text is saved with an `empty_asr` placeholder transcript so the meeting remains visible, exportable, and reviewable.

### Semantic Segmentation And Speaker Inference After ASR

SoloRecord handles speaker splitting in three layers:

1. Prefer native speaker fields returned by ASR, such as `speaker_id`, `speaker`, `spk`, `spk_id`, or `speakerLabel`.
2. If ASR returns only plain text, a single speaker, or contextual call-outs, the server calls the configured LLM to re-segment the transcript and infer speakers from names, colons, task ownership, topic continuation, references, and surrounding context.
3. After the LLM returns, the server still runs a residual split pass. If one row still contains “Alice said/Bob:/Alice please cover” style mixed turns, or one named call-out followed by a same-row reply such as “I will handle it”, it splits those turns and keeps `speaker_review`. Host preface text before a call-out stays with the original speaker so it is not misassigned to the first called person.
4. If the LLM is unavailable, the server uses lightweight rules for clear markers such as “Alice said” or “Bob:”. It also conservatively handles a named call-out followed by first-person replies or same-topic deliverable/deadline updates, while keeping review flags because this is not voiceprint confirmation.

Configuration switch:

```text
SOLO_ENABLE_SEMANTIC_SEGMENTATION=true
```

Operations notes:

- This feature benefits from an LLM provider. If the LLM is not configured, transcription still succeeds and falls back to rule-based splitting.
- FunASR/OpenAI-compatible requests include `diarization=true`, `speaker_diarization=true`, and `spk_model=cam++`. If the ASR service returns speaker fields inside `sentence_info` or `segments`, SoloRecord uses them directly.
- Some FunASR-compatible services tested during integration returned only `text` without speaker fields. In that case, LLM semantic segmentation is the main compensation layer. Even with native speaker IDs, named call-outs and same-topic continuations can still trigger context-based review hints.
- Multi-source final processing merges duplicate evidence across sources, but source rows that disagree on dates, amounts, or owners are kept as `multi_source_conflict`. During acceptance, replay those sources before knowledge-platform ingestion.
- The Web transcript timeline marks rows as “needs review”, “LLM segmented”, or “rule segmented”. “Needs review” means the inferred speaker should be checked after the meeting.
- Each uploaded segment gets partial post-processing first and is marked with `semantic_partial`. When the meeting is finished, the server uses full-meeting context to rewrite the final timeline, summary, and action items with `semantic_final`.
- If a user has already corrected a `speaker_id` to a concrete name, final processing preserves that correction. Generic old names such as `Speaker 1/2/3` do not block new model-inferred names.
- The meeting detail quality panel shows action evidence coverage. Low coverage or an “action item lacks transcript evidence” issue means an action may have been hallucinated or weakly linked, so operators should review the transcript/audio before sharing it.
- LLM summaries are not saved blindly. The server first checks whether summary and role-note claims are supported by transcript evidence. If evidence coverage is too low, it replaces the result with a conservative transcript-grounded summary and corrects clearly unsupported action owners when stronger transcript evidence exists. Seeing the "conservative transcript-grounded summary" title means the safety fallback was used.
- If an action owner is a pronoun such as “I”, “we”, “he”, “this side”, or “everyone”, SoloRecord tries to replace it with a concrete speaker from first-person transcript evidence and task keywords. If it cannot, the owner becomes `待确认` and should be reviewed before IM sharing.
- If `speaker_evidence_weak_count` is above zero, some speaker names were not supported by original ASR text or original speaker labels. During acceptance, play those segments first and confirm the model did not turn topics, time phrases, or misheard words into names.
- If `speaker_alias_conflict_count` is above zero, one display name maps to multiple `speaker_id` values. Web shows this as a same-name/multiple-label warning, and the knowledge graph merges the person node while preserving original IDs for traceability.
- `knowledgeGraph` includes topic nodes linking “speaker discussed topic”, “topic produced action”, and “action has due date”. Topics are lightweight context helpers from transcripts and action items; transcript evidence remains the source of truth.

### Multi-Source Recording Acceptance

Multi-source recording is for large rooms or multiple participants recording at the same time. Shared meeting-code join is implemented; Web recorder and upload screens show server-side joinable meeting candidates and fill the code after a click. Nearby automatic device discovery is not implemented yet and should not be promised during deployment.

Acceptance steps:

1. Use account A to create a meeting with a meeting code such as `ROOM0601` and source label `front phone`.
2. Use account B to open the Web recorder or file-upload screen. It should show the meeting as a joinable candidate and fill `ROOM0601` after a click, without exposing transcripts, summaries, audio, or action items before joining.
3. Use account B on another device with the same meeting code and source label `back phone`.
4. Upload local segment 1 from both devices. The server should create two `audio_segments` with different global `segment_no` values, while both keep `source_segment_no=1` and different `source_id` values.
5. Web meeting detail should show multiple recording sources and multiple audio segments. Both audio files should be downloadable/playable by authorized users.
6. After finish, duplicated captured speech should increase `multi_source_merged_count`. Divergent key facts, such as dates, amounts, or owners, should increase `multi_source_conflict_count` and appear in quality review hints. Parallel turns captured by different devices should remain ordinary single-source evidence, not false conflicts.
7. `/api/external/meetings/{meetingId}/transcript?include_history=true` should expose `source_id`, `source_segment_no`, `qualityReport`, and `knowledgeReadiness`.

Troubleshooting notes:

- `max_sources` is clamped to 1-8 and enforced on upload as well as explicit source creation. HTTP 409 usually means the meeting source limit was reached. Full, ended, ready, or failed meetings are not returned by the joinable meeting discovery API.
- In multi-source meetings, coverage must be checked by `(source_id, source_segment_no)`, not by local segment number alone.
- Web timeline filters and action/summary evidence “jump to transcript” links also target `(source_id, source_segment_no)`. If two devices both have segment 1, each should jump to its own source; if it does not, first check whether the frontend payload lost `source_id`.
- `multi_source_conflict` is not a processing failure; it means a human should listen to the different sources for that time window.
- `qualityReport.multiSourceConflicts` is the concrete replay checklist for those conflicts. Each item includes source, source segment, time range, speaker, conflict text, and nearby conflicting snippets; downstream knowledge or operations agents should consume it before deciding whether the meeting is safe to index.
- `knowledgeReadiness.reviewEvidence` groups the human-review targets in one field: multi-source conflicts, weak coverage segments, speaker risks, summary risks, and action risks. Use it to locate issues quickly, then verify against the transcript evidence.
- If an action shows `evidenceStatus=conflict` or the "multi-source conflict" review label, the action has transcript evidence but the sources disagree on key facts such as date, amount, or owner. `knowledgeSafe=false` and `requiresReview=true` mean downstream reminder or knowledge platforms must not auto-send or store it as confirmed knowledge.
- If an action shows `evidenceStatus=majority` or the "majority source confirmed" label, the primary result is supported by most recording sources while a minority conflict still exists nearby. `knowledgeSafe=true` and `requiresReview=true` mean downstream systems may use it as primary evidence, but should preserve a replay-review hint.

### LLM Provider

Mock mode produces placeholder summaries:

```text
SOLO_LLM_PROVIDER=mock
```

Ollama:

```text
SOLO_LLM_PROVIDER=ollama
SOLO_LLM_ENDPOINT=http://127.0.0.1:11434
SOLO_LLM_MODEL=qwen3
```

OpenAI-compatible API:

```text
SOLO_LLM_PROVIDER=openai-compatible
SOLO_LLM_ENDPOINT=https://model.example.com/v1
SOLO_LLM_API_KEY=
SOLO_LLM_MODEL=qwen3
```

Real keys belong only in `server/.env` or a secret manager, never in the APK or public repository.

### External API And ES/OpenSearch

Hermes or other internal systems can pull records with:

```text
SOLO_EXTERNAL_API_TOKENS=hermes:replace-with-long-random-token,crm:another-token
```

Endpoints:

```text
GET /api/external/meetings
GET /api/external/meetings/{meetingId}
```

ES/OpenSearch is optional:

```text
SOLO_ES_ENABLED=true
SOLO_ES_URL=http://127.0.0.1:9200
SOLO_ES_INDEX=solorecord_meetings
SOLO_ES_API_KEY=
SOLO_ES_USERNAME=
SOLO_ES_PASSWORD=
```

It is an index only. The database remains the source of truth.

### Client Publishing

Admins upload client packages from the Web admin page:

- Platform: Android APK, Windows EXE/ZIP, macOS DMG, iOS IPA, or HarmonyOS HAP
- Version name, such as `0.7.0`
- Version code, integer and increasing
- Release notes
- Force update flag
- Package file

There are two APK build modes:

1. Public GitHub Release attachment: contains no real server URL or secret. Users enter the server URL on the Login Status tab. This is suitable for first install, integration testing, and public source sharing.
2. Internal company APK: embeds only the server URL and never embeds tokens or keys.

Internal build example:

```powershell
& 'C:\Users\Andy\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat' assembleDebug -PSOLO_SERVER_ENDPOINT=https://record.example.com
```

Output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

Users download client packages from the Web App Download page. After reinstall, users sign in and click server recovery. Server audio can be downloaded and played according to permissions.

Windows client build:

```powershell
cd clients\desktop
npm install
$env:SOLO_SERVER_URL="https://record.example.com"
npm run pack
npm run portable:win
```

Output:

```text
clients/desktop/release/SoloRecord-0.7.0-windows-x64.zip
```

After extracting the Windows ZIP, run `SoloRecord.exe`. If the build machine has the required electron-builder privileges, `npm run dist:win` can generate an NSIS installer EXE.
`portable:win` writes `SOLO_SERVER_URL` to `server-url.txt`; only the server URL may be embedded, never tokens or keys.

macOS DMG should be built on macOS from `clients/desktop`, or from the SwiftUI shell in `clients/macos`. iOS IPA uses the WKWebView shell in `clients/ios` and Xcode signing. HarmonyOS HAP uses DevEco Studio with `clients/harmony/SoloRecord`. See `docs/multi-platform-clients.md`.

Weak-network sync behavior:

- Android writes continuous WAV rolling audio segments to private local storage before sync.
- Segment duration is controlled by the Web/server configuration and defaults to about five minutes. Adjacent segments keep about two seconds of overlap to avoid losing words at segment boundaries.
- Upload uses the multipart file endpoint `POST /api/mobile/meetings/{meetingId}/segments`, not whole-file Base64 JSON.
- After each segment is accepted, the server immediately runs ASR for that segment and appends partial transcript rows to the same meeting record.
- The client keeps a local per-segment upload ledger. After the server confirms a segment, it is immediately marked uploaded.
- The next sync skips uploaded segments and sends only pending segments.
- This is segment-level resume, not byte-offset resume inside a single file. Retry cost is bounded to the current unconfirmed segment.
- `/finish` is retry-safe. If a queued, running, or completed processing job already exists, the server reuses that job instead of spending ASR/LLM again.
- If all segments already have online partial transcripts, final finish reuses those rows to generate the full summary and action items instead of running whole-meeting ASR again.

### Data And Backup

Default paths:

```text
var/solorecord.db
var/storage/
var/apk/
```

Back up:

- `var/solorecord.db`
- `var/storage/`
- `var/apk/`
- `server/.env`

Do not share `server/.env` externally or include it in images/public repositories.

### Health Check

```text
GET /api/health
```

Expected:

```json
{"status":"ok","app":"SoloRecord"}
```

### Troubleshooting

LDAP login failures usually point to `SOLO_LDAP_SERVER`, `SOLO_LDAP_BIND_DN_TEMPLATE`, `SOLO_LDAP_SEARCH_DN`, `SOLO_LDAP_SEARCH_FILTER`, TLS trust, or the user's LDAP password. Browser SSO failures usually point to `SOLO_BASE_URL`, `SOLO_SSO_REDIRECT_URI`, Synology callback configuration, or reverse proxy Host/TLS settings.

Sync failures usually point to the APK server endpoint, network access, expired token, or `GET /api/mobile/sync`.

### Go-Live LLM Quality Probe

Run these commands on at least one real completed meeting before handoff:

```bash
docker compose exec -T solorecord python -m solorecord_server.quality_probe --meeting-id <meeting_id>
docker compose exec -T solorecord python -m solorecord_server.quality_probe --meeting-id <meeting_id> --postprocess
docker compose exec -T solorecord python -m solorecord_server.quality_probe --meeting-id <meeting_id> --run-llm
```

All three modes are read-only. Check `qualityReport.status`, candidate people, `speaker_review_count`, timeline repair count, generic owners, and action owner evidence. In simulation modes, also inspect `delta.improved_metrics`, `delta.regressed_metrics`, `delta.speaker_names_added`, and `delta.suggested_owner_changes` to confirm mixed turns decrease, speakers become more complete, and action owner suggestions match the meeting context.

Transcription failures usually point to `SOLO_ASR_PROVIDER`, `SOLO_ASR_COMMAND`, `SOLO_ASR_ENDPOINT`, `SOLO_ASR_MODEL`, command execution permission, invalid JSON stdout, upstream STT HTTP errors, or `processing_jobs.error_message`.

Empty summaries usually point to missing `SOLO_LLM_PROVIDER`, `SOLO_LLM_ENDPOINT`, `SOLO_LLM_MODEL`, or `SOLO_LLM_API_KEY`. If the LLM is not configured, SoloRecord falls back to mock summaries.

For CJK PDF rendering issues, build the production image with:

```bash
docker compose build --build-arg INSTALL_MEDIA_TOOLS=true solorecord
```

### Go-Live Checklist

- `SOLO_SECRET_KEY` changed.
- `SOLO_ALLOW_DEMO_LOGIN=false`.
- HTTPS enabled.
- LDAP login verified with a test user.
- SSO callback verified if browser SSO/OIDC is enabled.
- ASR command or service verified.
- LLM configuration verified.
- `var/` mounted to persistent disk.
- Backups configured.
- External API tokens replaced with long random values.
- Required client packages uploaded and downloadable.
- Client packages confirmed to contain only the server URL, with no ASR/LLM/LDAP/SSO/Hermes/ES token or key.
- Test user completes LDAP login, recording, upload, transcription, speaker rename, export, server recovery, and server audio playback.
- `scripts\smoke-e2e.ps1` passed.
- `pip-audit -r server/requirements.txt` shows no known vulnerabilities.
