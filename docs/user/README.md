# SoloRecord 使用手册

## 这是什么

SoloRecord 是公司内部会议记录系统。你可以用手机录音，系统会把录音上传到服务器，生成转写、会议纪要和待办事项。你也可以在网页上查看、修改、导出会议记录。

## 你需要准备什么

- Android 手机，或 Windows/macOS/iOS/HarmonyOS 终端。
- 公司统一登录账号。
- SoloRecord 服务器地址。
- 公司内部分发的 Android APK、Windows 包、macOS 包、iOS IPA 或 HarmonyOS HAP。

## 安装终端应用

1. 打开 SoloRecord Web 页面。
2. 登录。
3. 进入“App 下载”。
4. 选择你的平台。
5. 下载并安装对应发布包。

如果手机提示“禁止安装未知来源应用”，按公司 IT 指引允许安装。

Windows 版本下载后解压，运行 `SoloRecord.exe`。iOS、macOS 和 HarmonyOS 需要公司签名包或企业分发通道。

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

多人同录时，所有参与录音的人在“会议编号”里填写同一个编号，例如 `0601A`；“录音源名称”建议写成“任旭手机”“会议室后排”“客户侧电脑”这类可辨识名称。系统会把 1-8 个录音源归集到同一场会议，各来源先独立上传和转写，整场结束后再由系统做多源校对、去重和冲突提示。不同设备不需要完全同一秒开始录音，晚几十秒开始通常也能被系统按分段和文本对齐；但重要会议仍建议尽量同时开始，减少漏掉开场信息。

如果网络不好或误点了重复加入，同一账号、同一设备名和同一录音源名称会继续使用原来的录音源，不会额外占用名额。同一个人同时用手机和电脑录音时，请给两台设备填写不同的录音源名称。

录音时系统会滚动保存音频。即使会议较长，也会按小段保存，减少意外丢失风险。默认约 5 分钟一个分段，具体时长由服务器配置；相邻分段会保留约 2 秒重叠，减少分段边界丢词。

录音中页面会显示音频分段数、已上传数、待上传数和正在写入的当前段。当前段也会定期写入本地索引，WAV 文件头会边录边刷新；如果系统异常关闭，已写入的部分更容易被本机保留下来。下次打开 App 时，异常中断的当前段会转成待上传分段。正常结束录音时，最后一段会先保存到本机，再提交服务器处理。

如果录音时网络可用，每个分段完成后会自动上传到服务器，并返回该分段的阶段转写。你看到的仍然是同一条会议记录，转写内容会持续补充；点击结束录音后，系统再整理整场会议的完整纪要和待办。

如果关闭 App，录音会停止，并尽量保存当前音频段。

## 网络不好怎么办

录音先按分段保存在手机本地。网络稳定后再同步到服务器。

你可以在“录音”页点击：

```text
同步最新会议到服务器
```

如果同步失败，稍后重试即可。App 会记录已经上传成功的分段，下次只继续上传未完成分段。不要在同步完成前手动清理 App 数据。

当前是“分段级断点续传”：一个分段上传成功后不会重复上传；如果某个分段上传到一半断网，需要重新上传这一小段。系统默认滚动分段较短，目的是把弱网重传成本控制在单个分段内。

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

如果系统已经根据上下文拆出了“任旭”“李娜”这类名字，但旁边标记了“需确认”，说明这是模型推断结果，建议你重点看这一段原文和音频。Web 时间线还可能显示“大模型分段”或“规则分段”，它们表示系统在 ASR 之后又做了一次对话轮次整理。

Web 详情页的“整理质量”会提示候选人名、需要校对的段落、发言人证据风险、分段覆盖率和待办证据率。待办证据率不是最终评分，而是提醒你：待办是否能在转写原文里找到依据。分段覆盖率用于发现某个音频分段在最终转写里过短或缺失；如果系统补出“系统复核”转写行，表示这段音频已上传但缺少有效转写，需要回听或重新转写。这类行只是定位复核入口，不会被当成发言人、纪要依据、待办依据或图谱事实。若出现“发言人缺少原文证据”“音频分段待核对”“待办缺少转写证据”或“待办与原文相反”，建议先回看对应转写或录音，再复制给 IM 或外部系统。

如果开启了多源同录，“整理质量”还会显示“多源合并”“多源互补”和“多源冲突”。多源合并表示系统发现多个录音源在同一时间记录了相近内容，并保留了更完整的一条；多源互补表示不同录音源各自漏掉了部分短语，系统把原始转写里能互相印证、且没有事实冲突的短语补到同一条记录中；多源冲突表示同一时间不同来源差异较大，或日期、数量、负责人等关键事实不一致，建议回听对应录音后再对外发送纪要。

如果某台设备晚一点开始录音，整理质量里可能看到“错峰对齐”的多源合并标记。这表示系统认为它和另一台设备记录的是同一段话，并已去重；如果关键日期、数量或负责人不一致，系统不会自动合并，会保留多条冲突证据让你确认。

多源同录下，Web 的转写筛选和“定位转写”会按“录音源 + 该设备自己的分段号”定位。两台设备都上传“第 1 段”时，系统会分别显示到对应录音源，不会把不同设备的第 1 段混在一起。

如果纪要标题出现“基于转写原文的保守整理”，说明系统发现大模型原始纪要证据不足，已经自动换成更贴近转写原文的版本。这个版本可能不够漂亮，但更适合先复核、再对外发送。如果其中出现“多源冲突待确认”，说明不同录音源对同一关键事实不一致，系统只是把冲突原文列出来供你回听，不代表已经判断哪一条正确。系统也会在保存新生成待办前删除完全找不到转写依据的模型待办；如果全部模型待办都缺证据，会保留一条带原文片段的“按转写原文复核待办”，提醒你先看原文，而不是直接发起督办。如果当前只是没有配置大模型，但 ASR 已经生成了真实转写，系统只会保留保守纪要，不会自动塞入“检查转写结果”待办；只有占位转写、空语音或缺音频这类情况才会显示复核提醒。Web 会把这类条目标成“系统复核提醒”，复制待办时会自动跳过；如果确实要形成督办，请先把它改写成真实负责人和真实任务。

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

如果识别不准确，可以在 Web 端编辑。Web 端的会议详情页可以新增、删除和修改待办；保存后，手机同步、导出文件和企业知识平台接口都会读取更新后的待办。

## 会后校对顺序

建议按这个顺序检查会议：

1. 看顶部状态和分段数量，确认没有待上传分段。
2. 播放关键录音分段，确认音频可用。
3. 修改说话人名称。
4. 检查会议纪要是否符合真实结论。
5. 检查待办的负责人、任务、截止时间和状态。
6. 用说话人或音频分段筛选转写，校对关键原文。
7. 导出或交给企业知识平台。

## Web 和桌面端怎么用

打开 SoloRecord Web 页面后，可以做这些事：

- 登录。
- 在“录音”页直接录音，或补传已有音频文件。
- 多源同录时填写相同会议编号，并为每个录音设备填写录音源名称。
- 查看会议列表。
- 搜索会议标题、纪要、转写正文。
- 查看会议详情。
- 修改会议标题。
- 修改会议纪要。
- 修改分角色整理。
- 修改待办负责人、任务、截止时间和状态。
- 查看待办证据；如果系统给出“建议负责人”，可以先应用建议，再保存待办。证据旁边的“定位转写”可以跳到对应原文段落，方便回听和校对。
- 检查待办里的“协同：某人”。这表示主责人明确，但转写里还有配合或协助关系，复制到 IM 前建议一并保留。
- 打开“本体图谱”。图谱会把人员、地点、时间、事项和待办显示成可拖动、可点击的关系图，例如“张三负责补充报价明细”“补充报价明细截止周三”“合同条款关联销售工作区”。点击节点或关系可以查看对应转写或待办证据。图谱用于查阅和知识整理，最终事实仍以转写原文和人工校对为准。
- 修改转写文本。
- 批量修改说话人名称。
- 按说话人或音频分段筛选转写时间线。
- 加载并播放服务器上的录音分段。
- 导出 Markdown、Word、PDF、JSON、SRT。
- 下载 Android、Windows、macOS、iOS、HarmonyOS 发布包。

管理员还可以：

- 配置 ASR/LLM 模型。
- 查看处理任务。
- 重试失败任务。
- 上传新版本终端应用。

## 导出文件

会议详情页支持导出：

- Markdown：适合发给同事或放进知识库。
- Word：适合正式文档。
- PDF：适合归档。
- JSON：适合系统对接。
- SRT：适合字幕和时间轴。

如果导出文件里出现“系统复核提醒”，它只是提醒你补齐或复核记录，不是会议产生的待办。Markdown、Word、PDF 和 JSON 会把这类条目单独标出；复制给 IM 或同步督办前应跳过，除非你已经根据转写或录音把它改写成真实负责人和任务。

## 常见状态

| 状态 | 含义 |
| --- | --- |
| 本地已保存 | 手机已经保存录音，还没完全处理 |
| 已上传 | 音频已到服务器 |
| 分段转写中 | 已有部分分段完成转写，完整会议仍在补充 |
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

如果“整理质量”里出现“纪要与原文相反”，说明系统找到了相关转写，但纪要把“未完成/不要发/还没确认”写成了“已完成/已发送/已确认”等相反意思。这类风险比普通“纪要待核对”更高，应先点“定位转写”回到原文或回听录音，按原文改写后再复制纪要或让知识平台入库。

### 待办负责人不准怎么办？

先看待办下面的证据提示。“负责人证据弱”表示任务内容能在转写里找到，但负责人可能不对；即使该任务被多数录音源确认，也不能直接拿去督办。“缺转写证据”表示任务本身在转写里找不到可靠依据，优先按缺证据处理，系统不会再把同一条待办重复算成负责人证据弱。“待办与原文相反”表示原文可能是“先不要、暂缓、不能、取消”，但待办被写成了执行动作，比如原文说“先不要发客户通知”，待办却是“发送客户通知”。这种情况要先按原文改写或删除，不能直接复制给 IM 或同步给督办系统。如果看到“按转写原文复核待办”，说明模型原始待办被系统判定为缺证据或不安全，请先按旁边的原文片段重新整理真实待办。可以点击证据旁边的“定位转写”跳到原文。如果出现“建议负责人”，可以点击单条“应用建议”，也可以点击“应用全部建议负责人”批量填入，再保存待办。建议负责人会参考“某某你说/某某你那个部分/某某后面看”这类点名句，即使当前段落还没完全拆开，也会尽量避免把任务归给主持人；但建议负责人只是辅助判断，重要会议仍建议结合转写或录音确认。

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

- Android phone, or a Windows/macOS/iOS/HarmonyOS client.
- Company unified login account.
- SoloRecord server address.
- The company-distributed Android APK, Windows package, macOS package, iOS IPA, or HarmonyOS HAP.

### Install The Client

1. Open the SoloRecord Web page.
2. Sign in.
3. Open the App Download section.
4. Select your platform.
5. Download and install the matching package.

If Android blocks unknown-source installation, follow the company IT instructions.
On Windows, unzip the package and run `SoloRecord.exe`. iOS, macOS, and HarmonyOS require company-signed packages or enterprise distribution.

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

For multi-source recording, every recorder should enter the same meeting code, for example `0601A`. Use a recognizable source name such as "Renxu phone", "back of meeting room", or "customer laptop". The server groups 1-8 recording sources into one meeting. Each source uploads and transcribes independently, then final processing merges duplicate evidence and flags conflicts, including disagreements on dates, amounts, or owners. Recorders do not have to start at the exact same second; a device that starts tens of seconds late can usually still be aligned by segment and text, but important meetings should still start all recorders as close together as possible.

If the network is unstable or you tap join again, the same account, device name, and source name reuse the existing recording source instead of consuming another slot. If one person records with both phone and laptop, use different source names for the two devices.

The app saves audio in rolling segments while recording. The default is about five minutes per segment, controlled by the server. Adjacent segments keep about two seconds of overlap to reduce boundary word loss. Long meetings are split into smaller files to reduce loss risk. If the app is closed, recording stops and the current segment is preserved as far as possible.

During recording, the screen shows segment count, uploaded count, pending count, and the segment currently being written. The current segment is checkpointed into the local index, and the WAV header is refreshed while recording. If the system closes the app unexpectedly, already written audio is easier to recover. On next launch, the interrupted open segment becomes a pending upload segment. On normal stop, the last segment is saved locally before server processing starts.

When the network is available, each completed segment is uploaded and transcribed into the same meeting record. The transcript keeps growing during the meeting. After you stop recording, the server produces the full meeting summary and action items.

### Bad Network

Recordings are saved as local rolling segments first. They sync to the server when the network is stable.

You can tap:

```text
Sync latest meeting to server
```

If sync fails, retry later. The app remembers which segments were accepted by the server and uploads only pending segments next time. Do not uninstall the app or clear app data before sync completes.

This is segment-level resume. A segment that already reached the server is skipped on retry. If the network drops midway through a segment, that small segment is uploaded again. Rolling segments keep the retry cost bounded.

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

If the summary starts with "conservative transcript-grounded summary", the
original LLM summary did not pass evidence checks and the server replaced it
with a plainer transcript-grounded version. Newly generated action items that
have no transcript evidence are removed before saving. If the conservative
summary says "multi-source conflict pending confirmation", replay the matching
audio before treating that claim as true. If all generated actions are
unsupported, the system keeps one transcript-referenced review action so you
know to inspect the source text before sending reminders.
If no LLM is configured but ASR produced real transcript text, the system keeps
the conservative summary and does not create a synthetic "check transcript"
action. That review action is only kept for placeholder, empty-speech, or
missing-audio transcript rows.
Those fallback rows are shown as system review reminders. They are skipped when
you copy action items for IM, so turn them into a real owner/task only after
checking the transcript or audio.

Action items usually include:

- Owner
- Task
- Due date
- Status

If the result is inaccurate, edit it on the Web. The Web meeting detail page can add, remove, and update action items. Saved action items appear in mobile sync, exports, and enterprise knowledge APIs.

When an export shows a "system review reminder", treat it as a review prompt,
not a meeting action item. Markdown, Word, PDF, and JSON exports keep that label
so you do not copy it into IM reminders by accident.

### Post-Meeting Review Order

Recommended review flow:

1. Check the top status and segment counts to confirm nothing is pending upload.
2. Play key audio segments to confirm audio availability.
3. Rename speakers.
4. Check whether the summary matches the actual meeting decisions.
5. Check action owners, tasks, due dates, and status.
6. Filter the transcript by speaker or audio segment to review key evidence.
7. Export or let the enterprise knowledge platform ingest the record.

### Web And Desktop Usage

The SoloRecord Web app supports:

- Login/logout
- Live recording from the Recording page, or uploading an existing audio file
- Multi-source recording by sharing the same meeting code across devices
- Meeting list
- Search by title, summary, transcript, or keyword
- Meeting details
- Title editing
- Summary editing
- Action-item editing for owner, task, due date, and status
- Ontology graph review for people, places, times, matters, action items, and their relationships
- Transcript editing
- Batch speaker rename
- Transcript filtering by speaker or source audio segment
- Authorized playback of server-side audio segments
- Export to Markdown, Word, PDF, JSON, and SRT
- Android, Windows, macOS, iOS, and HarmonyOS downloads

Admins can also configure ASR/LLM providers, view jobs, retry failed jobs, and upload new client versions.

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
| Partial transcript | Some segments already have transcript text; the full meeting is still being completed |
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

If a row is marked “needs review”, the speaker was inferred from context and should be checked against the text or audio. Rows can also be marked “LLM segmented” or “rule segmented”, meaning SoloRecord reorganized the ASR text into dialogue turns after transcription.

The Web detail page includes a quality panel with candidate names, rows needing review, speaker-evidence risk, and action evidence coverage. This is a review aid: if a speaker lacks source evidence, an action item lacks transcript evidence, or an action owner is marked weak, check the transcript or audio before sending it to IM or another system. Unsupported actions are shown as missing transcript evidence and are not also counted as weak-owner issues. A majority-source task still needs owner confirmation when it is marked weak. Suggested owners may come from named call-outs such as “Yitian, cover automated testing” even before the row is fully split; treat the suggestion as a review aid and save the action list after applying it.

Open the ontology graph from the meeting detail page to review extracted
people, places, times, matters, action items, and relationships. The graph is
draggable and clickable; selecting a node or relationship shows the transcript
or action evidence behind it. Use it to understand context and prepare knowledge
ingestion, but keep transcript evidence and human corrections as the source of
truth.

If the quality panel shows weak source-segment coverage or a "system review" transcript row, that audio segment is uploaded but lacks effective transcript text. Replay or re-transcribe it before copying the summary or sending the meeting to another system.

In multi-source meetings, Web transcript filters and “jump to transcript” links use both the recording source and that device's local segment number. If two devices both upload segment 1, SoloRecord keeps them separate in review and evidence navigation.

If one device starts recording late, the quality panel may show a time-aligned multi-source merge. That means SoloRecord believes two sources captured the same speech and removed the duplicate. If key facts disagree, it keeps separate conflict evidence instead of merging automatically.

The quality panel may also show a multi-source complementary merge. This means different recorders captured non-conflicting fragments of the same speech, and SoloRecord kept the original-source phrases together in one row. Review it like normal transcript evidence before sending the summary externally.

What if the summary is inaccurate?

Check the transcript first. Fix transcript errors, then regenerate or edit the summary.

If the quality panel shows "summary contradicts transcript", SoloRecord found transcript evidence on the same topic but the summary reversed the meaning, such as turning "not sent yet" into "sent". Review the linked transcript or audio before copying the summary or sending it to a knowledge base.

If an action item is missing after regeneration, check whether the transcript said to wait, pause, cancel, or not perform that action yet. SoloRecord removes unsafe executable reminders that contradict the transcript, while keeping review tasks such as "confirm whether to send". Phrases like "wait for legal approval before sending" are shown as conditions, not automatic owner assignments to legal.

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
