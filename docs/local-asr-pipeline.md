# 本地 ASR 音频流水线

本文定义 SoloRecord 使用本地/私有 ASR 模型时的推荐音频处理架构。

## 结论

采用“SoloRecord 网关后接本地 ASR 服务”的架构。APK 只负责登录、可靠录音、本地播放、上传重试和记录展示。

APK 默认不承担重 VAD、降噪、说话人分离或 ASR。手机硬件和 Android 音频行为差异较大，重处理会和最重要的目标冲突：不能丢录音。

首个建议评估的 runtime 是 `sherpa-onnx`，因为它在 Apache-2.0 许可证下覆盖离线 ASR、VAD、说话人分离、标点和语音增强。开源对比见 `docs/open-source-research.md`。

## 职责拆分

### APK

- 用前台服务录音。
- 将音频滚动分段写入本地存储。
- 用户停止或关闭 App 时安全停止。
- 用同一个 meeting id 聚合一次开始/结束周期内的所有分段。
- 网络稳定后上传缺失分段；已被服务端确认的分段不重复上传。
- 按顺序播放本地音频分段。
- 同步后展示转写、纪要和待办。

### 网关 / 本地 ASR 服务

- 接收并持久化上传分段。
- 统一音频格式。
- 执行 VAD 和质量检测。
- 可选执行降噪和去混响。
- 可选执行说话人分离。
- 调用本地 ASR 模型。
- 将全部分段结果合并为会议时间线。
- 调用配置的大模型生成会议纪要和待办。
- 将最终结构化数据转发给 Hermes 或销售工作区。

## 音频流水线建议

### A. 必做：分段与质量控制

- APK 滚动分段，例如每 3 到 5 分钟一个文件。
- 服务端 VAD 去掉静音和明显非人声片段。
- 将音频统一到 ASR 模型要求的采样率、声道、采样精度和容器。
- 做基础响度、爆音和裁剪检测。
- 保存分段级元数据：时长、采样率、声道、平均音量、裁剪比例、VAD speech ratio、处理状态。

推荐默认：

```text
APK 输入：m4a/aac，优先 mono，16 kHz 或 48 kHz 均可
ASR 标准输入：wav/pcm，mono，采样率按模型要求
APK 滚动分段：3-5 分钟
VAD speech chunk：10-30 秒，带少量重叠
Overlap：300-800 ms，降低边界丢词
```

APK 滚动分段是可靠性边界；VAD chunk 是 ASR 处理边界。两者相关，但不是同一概念。

上传可靠性边界也是 APK 滚动分段。SoloRecord 当前实现的是分段级断点续传：一个分段上传成功后本地账本标记为 `uploaded`，弱网重试时跳过；如果单个分段上传中途断开，则重新上传该分段。只要保持 3 到 5 分钟分段，重传成本可控，且避免了手机端维护复杂字节 offset 状态。

### B. 常做：轻量降噪/去混响

降噪和去混响作为配置开关，不默认激进启用。

推荐先用：

- VAD + 格式统一。
- 真实会议录音 A/B 测试。
- 只有转写确实提升时才开启轻量降噪。

强降噪可能损伤数字、人名、口音和会议中的短确认词。

### C. 关键：说话人分离

说话人分离应是独立流水线阶段。除非 ASR 模型明确支持，否则不要假设 ASR 能稳定识别“谁说话”。

推荐流程：

1. 音频统一格式。
2. 执行 VAD。
3. 执行 diarization，得到 speaker 时间段。
4. 按时间段切 ASR chunk，并保留 overlap。
5. 执行 ASR。
6. 合并回全局时间线。
7. 由 LLM 结合转写上下文、参会人列表和销售工作区用户推断真实姓名与待办负责人。

先保存稳定匿名 speaker id，例如 `SPEAKER_01`。LLM 或人工修正层再映射为真实姓名。

## 数据模型建议

原始 ASR chunk 和用户可见的合并转写分开保存。原始 chunk 保留来源音频、VAD 起止时间、模型置信度和 runtime 信息；合并转写保存 speaker id、display name、全局时间戳和正文。

## 实施建议

第一版本地 ASR 只上 VAD 和格式统一。用真实会议录音验证后再决定是否开启降噪。若待办“到人”很关键，尽早加入 diarization，但必须保留人工可编辑，因为会议室音频不可能总是完美分离。

## English

# Local ASR Audio Pipeline

This document defines the preferred audio-processing architecture when
SoloRecord uses a local/private ASR model instead of a public cloud ASR service.

## Decision

Use a local ASR service behind the SoloRecord gateway. Keep the APK focused on
login, reliable recording, local playback, upload retry, and record display.

The APK should not run heavy VAD, denoise, diarization, or ASR by default. Phone
hardware and Android audio behavior vary too much, and heavy processing competes
with the most important job: never losing the recording.

Recommended first runtime to evaluate: `sherpa-onnx`, because it covers offline
ASR, VAD, diarization, punctuation, and speech enhancement with an Apache-2.0
license. See `docs/open-source-research.md` for the open-source comparison.

## Split of responsibility

### APK

- Records audio in a foreground service.
- Writes rolling segments to local storage.
- Stops safely on user stop or app close.
- Keeps a meeting id that groups all segments from one start/end cycle.
- Uploads missing segments when the network is stable; server-confirmed segments are not sent again.
- Plays local audio segments in order.
- Displays transcript, summary, and action items after sync.

### Gateway / local ASR service

- Receives and persists uploaded segments.
- Normalizes audio format.
- Runs VAD and quality checks.
- Optionally runs denoise and dereverb.
- Optionally runs speaker diarization.
- Calls the local ASR model.
- Merges all segment results into one meeting timeline.
- Calls the configured LLM for meeting notes and action items.
- Forwards the final structured payload to Hermes or the sales workspace.

## Audio pipeline

### A. Required: segmentation and quality control

Required steps:

- Rolling file segmentation from the APK, for example every 3 to 5 minutes.
- Server-side VAD to remove silence and obvious non-speech sections before ASR.
- Audio format normalization to the ASR model's expected sample rate, channels,
  sample width, and container.
- Basic loudness and clipping checks.
- Segment-level metadata: duration, sample rate, channels, average volume,
  clipping ratio, VAD speech ratio, and processing status.

Practical default:

```text
Input from APK: m4a/aac, mono preferred, 16 kHz or 48 kHz acceptable
Normalized ASR input: wav/pcm, mono, model-specific sample rate
Rolling segment size: 3-5 minutes
VAD speech chunk: 10-30 seconds with small overlap
Overlap: 300-800 ms to reduce boundary word loss
```

Important: the APK rolling segment is a safety boundary. VAD chunks are an ASR
processing boundary. They are related but should not be the same concept.

The upload reliability boundary is also the APK rolling segment. SoloRecord uses
segment-level resume: once a segment is accepted by the server, the local ledger
marks it `uploaded` and retries skip it. If the network drops midway through one
segment, that segment is uploaded again. Keeping segments around three to five
minutes bounds retry cost without adding byte-offset state on the phone.

### B. Common: light denoise and dereverb

Treat denoise and dereverb as optional filters controlled by configuration.

Start with:

- VAD + format normalization only.
- A/B test on real meeting recordings.
- Enable light denoise only if transcripts clearly improve.

Avoid aggressive denoise by default. It can damage numbers, names, accents, and
short confirmations such as "嗯", "对", "好", which are common in meetings.

Suggested gateway config:

```json
{
  "audioProcessing": {
    "vad": true,
    "denoise": "off",
    "dereverb": "off",
    "targetSampleRate": 16000,
    "chunkSeconds": 20,
    "overlapMillis": 500
  }
}
```

### C. Important: speaker diarization

Speaker diarization should be an independent pipeline stage. Do not rely on the
ASR model to always identify speakers unless that model explicitly supports it.

Recommended flow for meeting usefulness:

1. Normalize audio.
2. Run VAD.
3. Run diarization to produce speaker time ranges.
4. Cut ASR chunks by time range, preserving overlaps.
5. Run ASR.
6. Merge text back into a global timeline.
7. Ask the LLM to infer real names and action owners from transcript context,
   participant list, and known sales workspace users.

Diarization output should use stable anonymous speaker ids first:

```json
{
  "speaker": "SPEAKER_01",
  "startMillis": 10200,
  "endMillis": 18400,
  "confidence": 0.82
}
```

The LLM or user correction layer can later map `SPEAKER_01` to a real person.

## Meeting timeline model

Store raw ASR chunks and the merged user-facing transcript separately.

Raw chunk:

```json
{
  "meetingId": "meeting-id",
  "segmentNo": 3,
  "chunkNo": 12,
  "speaker": "SPEAKER_01",
  "startMillis": 913000,
  "endMillis": 928500,
  "text": "我们下周一之前把报价方案发出来。",
  "confidence": 0.91,
  "source": {
    "audioPath": "part_0003.m4a",
    "vadStartMillis": 13000,
    "vadEndMillis": 28500
  }
}
```

Merged transcript segment:

```json
{
  "speaker": "SPEAKER_01",
  "displayName": "待确认",
  "startMillis": 913000,
  "endMillis": 928500,
  "text": "我们下周一之前把报价方案发出来。"
}
```

## Gateway API additions

The existing mobile API can stay stable, but the gateway should expose
processing state clearly:

```text
POST /mobile/meetings/{meetingId}/segments/{segmentNo}
POST /mobile/meetings/{meetingId}/finish
POST /mobile/meetings/{meetingId}/process
GET  /mobile/meetings/{meetingId}/processing-status
GET  /mobile/meetings/{meetingId}/transcript
GET  /mobile/meetings/{meetingId}/summary
```

Processing statuses:

```text
recorded
uploading
uploaded
preprocessing
diarizing
transcribing
summarizing
forwarding
ready
failed
```

## Implementation order

The system should be deployed as a complete workflow, while individual modules
can be enabled progressively as models and real meeting samples become ready:

- APK rolling recording.
- Upload retry.
- Server-side format normalization.
- Server-side VAD.
- Local ASR.
- LLM summary and action items.
- Lightweight denoise/dereverb A/B testing.
- Audio quality dashboard.
- Processing retry per chunk.
- Transcript merge polishing.
- Speaker diarization.
- Speaker-name mapping.
- Manual correction in Records.
- Better owner assignment using sales workspace contacts.

## Practical recommendation

Build the first local ASR version with VAD and normalization only. Add denoise
only after testing real recordings. Add diarization early if action items must
be trusted by person, but keep its output editable because meeting-room audio is
never perfectly separated.
