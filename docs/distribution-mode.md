# Distribution Mode

分发版目标是让用户只执行录音、整理、推送，不在 App 内看到会议内容。

## 用户体验

- 首页只显示当前状态：准备录音、录音中、录音已保存、整理中、推送中、已推送
- 没有模型配置入口
- 没有会议列表
- 没有转写、纪要、待办正文
- 处理结果自动发送到预配置目标

## 数据留存

App 本地保存：

- 会议 ID
- 标题
- 创建时间
- 音频路径
- 状态

App 本地不保存：

- 分角色转写正文
- 分角色会议记录
- 会议纪要
- 待办事项

整理结果会在内存里短暂保留，并在整理完成后自动推送。推送成功后，本地只更新状态为 `pushed`。

## 预配置范围

APK 构建时只允许预配置服务器地址：

```text
SOLO_SERVER_ENDPOINT=https://record.example.com
```

转写模型、大模型、Hermes、OpenClaw、企业微信云文档、飞书云文档等接口地址和密钥都保存在服务器。这样即使 APK 被反编译，也不会泄露模型或外部系统凭证。

## English

# Distribution Mode

The original distribution-mode idea was to let end users only record, process, and push, without seeing meeting content inside the app.

The current V0.7 implementation is fuller: signed-in users can view records, transcripts, summaries, action items, and audio playback in the Android app and Web UI. This file remains as a reference for a stricter internal-distribution mode.

## User Experience

- The home screen shows only current status: ready to record, recording, saved, processing, pushing, pushed.
- No model configuration inside the app.
- No meeting list.
- No transcript, summary, or action-item body inside the app.
- Results are automatically sent to the preconfigured target.

## Data Retention

The app stores locally:

- Meeting ID
- Title
- Created time
- Audio path
- Status

The app does not store locally:

- Speaker-segmented transcript text
- Role-based meeting notes
- Meeting summary
- Action items

The processed result is held briefly in memory and pushed automatically. After a successful push, local status changes to `pushed`.

## Preconfiguration Scope

The APK build should only preconfigure the server endpoint:

```text
SOLO_SERVER_ENDPOINT=https://record.example.com
```

Transcription model, LLM, Hermes, OpenClaw, WeCom document, Feishu document, endpoints, and keys are stored on the server. If the APK is decompiled, model or external-system credentials are not exposed.
