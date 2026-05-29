# SoloRecord 使用手册

## 这是什么

SoloRecord 是公司内部会议记录系统。你可以用手机录音，系统会把录音上传到服务器，生成转写、会议纪要和待办事项。你也可以在网页上查看、修改、导出会议记录。

## 你需要准备什么

- Android 手机。
- 公司统一登录账号。
- SoloRecord 服务器地址。
- 公司内部分发的 APK。

## 安装 APK

1. 打开 SoloRecord Web 页面。
2. 登录。
3. 进入“App 下载”。
4. 下载 Android APK。
5. 手机上安装 APK。

如果手机提示“禁止安装未知来源应用”，按公司 IT 指引允许安装。

## 登录

打开 App 后进入“登录状态”页：

1. 填服务器地址。
2. 输入公司 LDAP 用户名和密码。
3. 点击“LDAP 登录”。

如果公司内部分发的 APK 已经预置服务器地址，这里会自动显示；如果是 GitHub Release 公开附件安装包，需要手动填写公司运维提供的服务器地址。

登录成功后，顶部会显示当前用户和服务器地址。

没有登录时，不能录音，也不能查看记录。

如果公司后续启用浏览器统一登录，也可以使用“浏览器统一登录”入口。

## 录音

进入“录音”页：

1. 点击“开始录音”。
2. 第一次使用时允许麦克风权限。
3. 会议结束后点击“结束录音”。

录音时系统会滚动保存音频。即使会议较长，也会按小段保存，减少意外丢失风险。

如果关闭 App，录音会停止，并尽量保存当前音频段。

## 网络不好怎么办

录音先保存在手机本地。网络稳定后再同步到服务器。

你可以在“录音”页点击：

```text
同步最新会议到服务器
```

如果同步失败，稍后重试即可。不要在同步完成前手动清理 App 数据。

## 查看记录

进入“记录”页：

- 可以看到本机已有会议。
- 点击“查看详情”。
- 可以查看音频分段、转写、纪要和待办。
- 本地录音段可以播放。

如果你重装了 App，本机记录会消失，但服务器记录还在。重新登录后，点击“从服务器恢复记录”即可把自己有权限的会议同步回手机。服务器记录里的音频可以点“下载并播放”。

## 修改说话人名字

转写里会先显示：

```text
发言人 1
发言人 2
```

如果你知道某个发言人是谁：

1. 在该段下面输入真实名字。
2. 点击“应用到该角色全部段落”。

系统会把同一个角色的所有段落一起改名。

例如把 `发言人 1` 改成 `张三`，后面所有 `发言人 1` 都会显示为 `张三`。

## 会议纪要和待办

系统会根据转写生成：

- 会议纪要
- 分角色整理
- 待办事项

待办通常包括：

- 负责人
- 任务
- 截止时间
- 状态

如果识别不准确，可以在 Web 端编辑。

## Web 端怎么用

打开 SoloRecord Web 页面后，可以做这些事：

- 登录。
- 查看会议列表。
- 搜索会议标题、纪要、转写正文。
- 查看会议详情。
- 修改会议标题。
- 修改会议纪要。
- 修改转写文本。
- 批量修改说话人名称。
- 导出 Markdown、Word、PDF、JSON、SRT。
- 下载 Android APK。

管理员还可以：

- 配置 ASR/LLM 模型。
- 查看处理任务。
- 重试失败任务。
- 上传新版本 APK。

## 导出文件

会议详情页支持导出：

- Markdown：适合发给同事或放进知识库。
- Word：适合正式文档。
- PDF：适合归档。
- JSON：适合系统对接。
- SRT：适合字幕和时间轴。

## 常见状态

| 状态 | 含义 |
| --- | --- |
| 本地已保存 | 手机已经保存录音，还没完全处理 |
| 已上传 | 音频已到服务器 |
| 排队中 | 等待服务器处理 |
| 预处理 | 服务器正在准备音频 |
| 转写中 | 正在生成文字 |
| 整理纪要 | 正在生成纪要和待办 |
| 已完成 | 可以查看结果 |
| 失败 | 处理出错，需要重试或联系管理员 |

## 常见问题

### 我能不能离线录音？

可以。录音会先保存在手机本地。转写和纪要需要同步到服务器后处理。

### App 关了还会录吗？

当前设计是关闭 App 后停止录音，避免用户误录。关闭时会尽量保存当前音频段。

### 重装 App 后记录还在吗？

服务器上的记录还在。重新登录后可以从服务器同步。手机本地未上传的录音如果在重装前没有同步，可能会丢失。

### 说话人识别错了怎么办？

在记录详情里手动改角色名，并应用到该角色全部段落。

### 纪要不准确怎么办？

先检查转写是否准确。转写有错时先改转写，再重新整理会议。

### 找不到某场会议怎么办？

在 Web 端搜索标题、关键词或转写正文。如果仍找不到，确认你是否用同一个账号登录。

### 同步失败怎么办？

检查：

- 手机网络。
- 服务器地址。
- 是否已登录。
- 服务器是否可访问。

然后重新点击同步。

### 为什么需要登录？

会议录音和纪要属于公司内部资料。登录用于确认身份，并决定你能查看哪些会议。

## 使用建议

- 会议开始前先确认已登录。
- 重要会议结束后尽快同步。
- 同步完成前不要卸载 App 或清理 App 数据。
- 生成纪要后检查说话人和待办负责人。
- 对外发送纪要前先人工确认敏感内容。

## English

### What This Is

SoloRecord is an internal company meeting recorder. You can record meetings on an Android phone, sync recordings to the server, and receive transcripts, meeting summaries, and action items. You can also review, edit, search, and export records on the Web.

### What You Need

- Android phone.
- Company unified login account.
- SoloRecord server address.
- APK distributed by the company.

### Install The APK

1. Open the SoloRecord Web page.
2. Sign in.
3. Open the App Download section.
4. Download the Android APK.
5. Install it on your phone.

If Android blocks unknown-source installation, follow the company IT instructions.

### Sign In

Open the Login Status tab:

1. Enter the server address.
2. Tap Login.
3. Complete company unified login in the browser.

If the internally distributed APK was built with the server URL, it appears automatically. If the APK came from the public GitHub Release asset, enter the server URL provided by operations.

After sign-in, the top area shows the current user and server address. You cannot record or view records before signing in.

Demo login is only for administrators and integration testing. For normal use, use the unified login button.

### Recording

Open the Recording tab:

1. Tap Start Recording.
2. Allow microphone permission on first use.
3. Tap End Recording when the meeting is over.

The app saves audio in rolling segments while recording. Long meetings are split into smaller files to reduce loss risk. If the app is closed, recording stops and the current segment is preserved as far as possible.

### Bad Network

Recordings are saved on the phone first. They sync to the server when the network is stable.

You can tap:

```text
Sync latest meeting to server
```

If sync fails, retry later. Do not uninstall the app or clear app data before sync completes.

### Records

Open the Records tab:

- View local meetings.
- Tap Details.
- View audio segments, transcript, summary, and action items.
- Play local audio segments.

If the app is reinstalled, local records disappear, but server records remain. Sign in again and tap server recovery to sync meetings you can access back to the phone. Server-side audio can be downloaded and played by permission.

### Rename Speakers

Transcript speakers may start as:

```text
Speaker 1
Speaker 2
```

If you know who a speaker is:

1. Enter the real name below that segment.
2. Tap Apply to all segments for this role.

The same speaker id is updated everywhere. For example, changing `Speaker 1` to `Alice` updates all matching transcript rows.

### Summaries And Action Items

The system generates:

- Meeting summary
- Notes by role
- Action items

Action items usually include:

- Owner
- Task
- Due date
- Status

If the result is inaccurate, edit it on the Web.

### Web Usage

The SoloRecord Web app supports:

- Login/logout
- Meeting list
- Search by title, summary, transcript, or keyword
- Meeting details
- Title editing
- Summary editing
- Transcript editing
- Batch speaker rename
- Export to Markdown, Word, PDF, JSON, and SRT
- Android APK download

Admins can also configure ASR/LLM providers, view jobs, retry failed jobs, and upload new APK versions.

### Export Formats

- Markdown: good for sharing or knowledge bases.
- Word: good for formal documents.
- PDF: good for archives.
- JSON: good for system integration.
- SRT: good for subtitles and timelines.

### Common Statuses

| Status | Meaning |
| --- | --- |
| Saved locally | Audio is saved on the phone but not fully processed |
| Uploaded | Audio reached the server |
| Queued | Waiting for server processing |
| Preprocessing | Server is preparing audio |
| Transcribing | Transcript is being generated |
| Summarizing | Summary and action items are being generated |
| Ready | Results are available |
| Failed | Processing failed; retry or contact an admin |

### FAQ

Can I record offline?

Yes. Audio is saved locally first. Transcription and summaries require server sync.

Does recording continue after I close the app?

The current design stops recording when the app is closed, to avoid accidental recording. The current segment is preserved as far as possible.

Are records still available after reinstalling the app?

Server records remain. Sign in again and recover records from the server. Unsynced local recordings may be lost if the app was uninstalled before sync.

What if the speaker is wrong?

Rename the role in record details and apply the change to all segments with the same speaker id.

What if the summary is inaccurate?

Check the transcript first. Fix transcript errors, then regenerate or edit the summary.

What if I cannot find a meeting?

Search by title, keyword, or transcript text on the Web. Also confirm you signed in with the same account.

What if sync fails?

Check phone network, server address, login state, and whether the server is reachable. Then retry sync.

Why is login required?

Meeting audio and summaries are internal company materials. Login confirms who you are and controls which meetings you can access.

### Tips

- Confirm you are signed in before important meetings.
- Sync important meetings soon after they end.
- Do not uninstall the app or clear app data before sync completes.
- Review speaker names and action owners after summaries are generated.
- Manually check sensitive content before sending summaries outside the meeting team.
