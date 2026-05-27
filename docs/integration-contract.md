# SoloRecord Integration Contract

SoloRecord 预留一个通用 HTTP Webhook，用来把会议记录推送给 Hermes Agent、OpenClaw Agent、企业微信云文档、飞书云文档或你自己的程序。

当前分发版 App 不在界面展示会议内容，也不把转写、纪要、待办正文写入本地历史文件。Webhook 是会议内容离开 App 的唯一标准出口。

## 1. 公网转写接口

App 配置项：

- `transcriptionEndpoint`
- `transcriptionApiKey`
- `transcriptionModel`

请求：

```json
{
  "model": "your-transcription-model",
  "audio_file_name": "meeting_20260525_103000.m4a",
  "audio_mime_type": "audio/mp4",
  "audio_base64": "...",
  "response_format": "speaker_segments_json",
  "requirements": "请返回分角色转写，字段为 segments: [{speaker,text,startMillis,endMillis}]。"
}
```

鉴权：

```http
Authorization: Bearer <transcriptionApiKey>
```

推荐响应：

```json
{
  "segments": [
    {
      "speaker": "张三",
      "text": "今天我们先看项目进度。",
      "startMillis": 0,
      "endMillis": 3600
    }
  ]
}
```

如果你的转写服务不能直接接收 Base64 音频，建议在公网部署一个轻量适配网关，由网关把 SoloRecord 的统一 JSON 转换为厂商协议。

## 2. 公网大模型接口

App 配置项：

- `llmEndpoint`
- `llmApiKey`
- `llmModel`

当前客户端使用 OpenAI-compatible Chat Completions 请求格式：

```json
{
  "model": "your-llm",
  "messages": [
    {
      "role": "system",
      "content": "你是会议纪要助手。只返回 JSON，不要 Markdown。"
    },
    {
      "role": "user",
      "content": "..."
    }
  ],
  "temperature": 0.2
}
```

模型消息里的 `content` 需要返回 JSON 字符串：

```json
{
  "roleNotes": "按发言人整理的会议记录",
  "summary": "会议纪要",
  "actionItems": [
    {
      "owner": "李四",
      "task": "整理下周演示材料",
      "due": "周五",
      "status": "open"
    }
  ]
}
```

## 3. 外部系统推送接口

App 配置项：

- `webhookEndpoint`
- `webhookApiKey`
- `webhookTarget`

请求：

```json
{
  "event": "solo_record.meeting.ready",
  "target": "hermes",
  "meeting": {
    "id": "uuid",
    "title": "会议 1",
    "createdAtMillis": 1780000000000,
    "audioPath": "/data/user/0/com.solorecord/files/audio/meeting.m4a",
    "status": "processed",
    "roleNotes": "按角色整理的会议记录",
    "summary": "会议纪要",
    "transcriptSegments": [
      {
        "speaker": "张三",
        "text": "今天我们先看项目进度。",
        "startMillis": 0,
        "endMillis": 3600
      }
    ],
    "actionItems": [
      {
        "owner": "李四",
        "task": "整理下周演示材料",
        "due": "周五",
        "status": "open"
      }
    ]
  }
}
```

`webhookTarget` 建议值：

- `hermes`
- `openclaw`
- `wecom-doc`
- `feishu-doc`
- `custom`

对企业微信云文档和飞书云文档，建议让 Webhook 网关负责 OAuth、文档创建、权限控制和重试，SoloRecord 只负责发送标准会议 JSON。
