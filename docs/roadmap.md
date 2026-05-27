# SoloRecord Roadmap

## MVP 已覆盖

- 本地会议录音
- 本地会议 JSON 存储
- 可配置公网转写接口
- 可配置公网大模型接口
- 分角色转写数据结构
- 分角色会议记录、会议纪要、待办事项数据结构
- 通用 Webhook 推送接口

## 建议下一阶段

- 增加会议标题编辑、搜索和删除
- 增加录音后台服务和前台通知，支持锁屏持续录音
- 增加音频分片上传，避免长会议 Base64 请求过大
- 增加本地 ASR 网关：格式统一、VAD、质量检测、本地模型转写
- 增加可配置轻量降噪/去混响，并用真实会议录音做 A/B 测试
- 增加说话人分离流水线，把匿名说话人时间线合并到会议记录
- 增加厂商适配器：OpenAI-compatible、阿里云、火山、讯飞、腾讯云、DeepSeek-compatible
- 增加推送适配器：Hermes Agent、OpenClaw Agent、企业微信云文档、飞书云文档
- 增加失败重试队列和推送状态日志
- 增加本地加密存储 API Key

## English

# SoloRecord Roadmap

## Covered By The Early MVP

- Local meeting recording.
- Local meeting JSON storage.
- Configurable public transcription endpoint.
- Configurable public LLM endpoint.
- Speaker-segmented transcript data structure.
- Role-based notes, meeting summary, and action-item data structures.
- Generic Webhook push interface.

## Suggested Next Enhancements

- Add meeting title editing, search, and delete.
- Add background recording service and foreground notification for lock-screen recording.
- Add chunked/resumable audio upload to avoid large Base64 requests for long meetings.
- Add local ASR gateway stages: format normalization, VAD, quality checks, and local model transcription.
- Add configurable light denoise/dereverb after A/B tests with real recordings.
- Add diarization and merge anonymous speaker timelines into meeting records.
- Add vendor adapters: OpenAI-compatible, Alibaba Cloud, Volcengine, iFlytek, Tencent Cloud, DeepSeek-compatible.
- Add push adapters: Hermes Agent, OpenClaw Agent, WeCom cloud docs, Feishu cloud docs.
- Add retry queues and push status logs.
- Add encrypted local API key storage if any client-side keys ever become unavoidable.

## V0.7 Note

V0.7 already includes many items from this roadmap: server-authoritative storage, Web/PC UI, APK publishing, rolling recording, mobile sync, protected server audio download, speaker rename, exports, provider configuration, local ASR command adapter, LLM adapter, external API, and optional ES/OpenSearch indexing.
