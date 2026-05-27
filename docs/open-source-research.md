# 开源调研记录

日期：2026-05-26

本文总结与 SoloRecord “群晖登录 Android 录音 + 本地 ASR 会议流水线”相似的开源项目和可复用组件。

## 简短建议

把开源组件作为依赖或适配器复用，不要克隆现成会议 App。

最适合复用：

- 本地 ASR/VAD/diarization runtime：`k2-fsa/sherpa-onnx`，Apache-2.0。
- 本地 Whisper runtime / ASR 基准：`ggml-org/whisper.cpp`，MIT。
- Web 转写架构参考：`pluja/whishper`，但 AGPL-3.0，不要直接复制代码。
- 桌面会议助手参考：`Zackriya-Solutions/meetily`，MIT。
- Android 滚动录音架构参考：`151henry151/listen`，GPL-3.0，不要复制代码。
- 简单 Android VAD 备选：`gkonovalov/android-vad`，MIT。
- 低资源 ASR 备用：`alphacep/vosk-api`，Apache-2.0。

SoloRecord 仍应保持自有 App 架构，因为它有群晖 SSO、会议聚合、上传重试、本地 ASR 服务、会议纪要、Hermes/销售工作区转发和企业部署要求。

## 候选项目概览

- `sherpa-onnx`：最强本地 ASR/VAD/diarization 候选，支持多平台和多语言绑定，适合先部署在本地网关/服务器。
- `whisper.cpp`：无需重 Python/PyTorch 栈的本地 Whisper 推理，适合作为 ASR 适配器和质量基准。
- `Vosk`：成熟、轻量，可做低资源 fallback。
- `WhisperX`、`pyannote.audio`、`NeMo`：适合实验和离线 benchmark，但生产部署更重。
- `Whishper`：Web 转写系统架构很接近，但 AGPL-3.0，仅做设计参考。
- `Meetily`：PC 桌面端参考，适合后续需要捕获 PC 麦克风和系统声音时评估。
- `HushNote`、`ownscribe`：验证“本地录音/转写/说话人标注/纪要/导出”的产品形态，可参考 UX。
- `android-vad` 和 `Android-Wave-Recorder`：可用于后续端侧人声提示、网络优化或改录 WAV/PCM 的评估。

## 架构经验

1. 不要耦合录音和 ASR。模型慢或不可用时，录音仍必须可靠。
2. Android 使用滚动音频文件、前台服务、分段管理、本地元数据和播放 UI。
3. 网关作为处理 owner，可跑重模型、统一格式、按段重试，并把模型密钥留在服务端。
4. VAD、diarization、ASR、summary 拆成独立阶段，方便重试和对比模型。
5. diarization 是概率结果，保存匿名 speaker id、置信度和修正状态，不假设系统总能知道真实姓名。
6. 代码复用优先 Apache-2.0/MIT；GPL/AGPL 项目只做架构参考，除非公司接受许可证义务。

## SoloRecord 组件选择

APK：

- 保持自研原生 Android Java/Kotlin。
- 使用前台 `RecordingService`。
- 本地保存会议和分段元数据。
- 未来可用 WorkManager 做上传重试。
- 初期使用 MediaRecorder M4A/AAC。
- 端侧 VAD 只作为可选 UX/诊断/网络优化。

本地网关 / ASR 服务：

- 优先用 `sherpa-onnx` 做 VAD + ASR 实验。
- 通过 sherpa-onnx 评估 SenseVoice/Paraformer/Whisper 类模型对中文会议音频的质量。
- 如果到人归因必须可靠，再加入 sherpa-onnx diarization。
- Vosk 作为小资源 fallback。
- pyannote/WhisperX 作为 benchmark 工具，不一定进入第一版生产 runtime。

会议智能：

- 原始 chunk 和合并转写分开保存。
- 保存模型名、版本、runtime、时间戳、置信度、VAD speech ratio、diarization confidence。
- 从合并时间线生成纪要和待办。
- 允许用户或管理员修正 speaker name。

## 复用优先级

1. 将 `sherpa-onnx` 作为依赖或 sidecar binary。
2. 借鉴 `Listen` 的 Android 前台录音和分段架构，但不复制 GPL 代码。
3. 仅在需要端侧 VAD 时使用 `android-vad`。
4. 参考 `ownscribe`/`HushNote` 的进度状态、输出格式和说话人标注。
5. 除非许可证策略改变，避免直接导入 GPL 会议 App 代码。

## English

# Open Source Research Notes

Date: 2026-05-26

This note summarizes similar open-source projects and reusable components for
SoloRecord's Synology-login Android recorder + local ASR meeting pipeline.

## Short recommendation

Use open-source components as libraries/adapters, not as an app clone.

Best fit:

- Local ASR/VAD/diarization runtime: `k2-fsa/sherpa-onnx` under Apache-2.0.
- Local Whisper runtime / ASR benchmark: `ggml-org/whisper.cpp` under MIT.
- Web transcription architecture reference: `pluja/whishper`, but do not copy
  code into a closed product because it is AGPL-3.0.
- Desktop meeting companion reference: `Zackriya-Solutions/meetily` under MIT.
- Android rolling recording architecture reference: `151henry151/listen`, but
  do not copy code because it is GPL-3.0.
- Simple Android VAD fallback: `gkonovalov/android-vad` under MIT.
- Optional low-resource ASR fallback: `alphacep/vosk-api` under Apache-2.0.

Keep our own app architecture because SoloRecord has different requirements:
Synology SSO, grouped meeting records, upload retry, local ASR service, meeting
minutes, Hermes/sales workspace forwarding, and enterprise deployment.

## Candidate projects

### sherpa-onnx

Repository: https://github.com/k2-fsa/sherpa-onnx

License: Apache-2.0

What it provides:

- Offline ASR
- VAD
- Speaker diarization
- Speaker identification
- Punctuation
- Speech enhancement
- Source separation
- Android, iOS, Linux, Windows, macOS, HarmonyOS support
- C/C++/Python/Java/Kotlin/Go/Rust/Swift bindings

Why it matters:

This is the strongest reusable base for the local ASR service. It avoids a
heavy PyTorch runtime, has Android/server deployment paths, and supports the
exact stages we need: VAD, ASR, diarization, and enhancement.

Recommended use:

- Use on the local gateway/server first.
- Consider Android on-device VAD/ASR later only for special offline scenarios.
- Pin versions and models. Run our own meeting-audio benchmark before upgrades.

### whisper.cpp

Repository: https://github.com/ggml-org/whisper.cpp

License: MIT

What it provides:

- C/C++ Whisper inference.
- Android, iOS, Linux, macOS, Windows, WebAssembly, and Raspberry Pi support.
- Quantized models and hardware acceleration options.
- VAD support.

Why it matters:

It is one of the most practical ways to run Whisper-style ASR locally without a
large Python/PyTorch stack. It is useful as a local ASR adapter and benchmark,
especially if the self-built ASR model needs a quality baseline.

Recommended use:

- Evaluate as a server-side ASR adapter.
- Keep VAD, diarization, and summary outside of `whisper.cpp` so the pipeline
  remains modular.
- Avoid making it the only path until Chinese meeting-audio quality and speed
  are benchmarked.

### Vosk

Repositories:

- https://github.com/alphacep/vosk-api
- https://github.com/alphacep/vosk-android-demo

License: Apache-2.0

What it provides:

- Offline ASR for Android, iOS, Raspberry Pi, and servers.
- Java/Python/Node/C#/C++ bindings.
- Android demo code.
- Speaker identification in the Android demo.

Why it matters:

Vosk is mature and small enough for low-resource devices. It is useful as a
fallback or baseline, especially when model size and predictable CPU use matter
more than maximum transcription quality.

Recommended use:

- Keep as a fallback adapter, not the primary meeting-ASR path.
- Benchmark Chinese meeting audio before choosing it.

### WhisperX / pyannote.audio / NeMo

Repositories:

- https://github.com/m-bain/whisperX
- https://github.com/pyannote/pyannote-audio
- https://github.com/NVIDIA-NeMo/NeMo

What they provide:

- WhisperX: Whisper transcription, word-level timestamps, alignment, and
  diarization integration.
- pyannote.audio: speaker diarization building blocks.
- NeMo: broader speech AI toolkit, including ASR and speaker-related pipelines.

Why they matter:

These are valuable benchmark and experimentation tools for the gateway side.
They are heavier than sherpa-onnx/whisper.cpp because they commonly bring a
Python/PyTorch deployment surface.

Recommended use:

- Use for experiments, evaluation, and offline benchmark jobs.
- Avoid putting them in the first production gateway unless the target server
  has enough CPU/GPU resources and deployment complexity is acceptable.

### Whishper

Repository: https://github.com/pluja/whishper

License: AGPL-3.0

What it provides:

- Self-hosted web UI for local audio/video transcription.
- Frontend, backend coordinator, transcription API, database, Nginx, and Docker
  Compose layout.
- Faster-Whisper backend, GPU/CPU support, subtitle editor, export to TXT, JSON,
  VTT, and SRT.

Why it matters:

It is the closest web-app architecture reference: separate transcription API,
backend, frontend, database, and reverse proxy. It validates that our PC/Web
side should be a browser app backed by the same server pipeline, not a separate
standalone product.

Reuse caution:

AGPL-3.0 is a strong network-copyleft license. Even for internal deployment, do
not copy its source into SoloRecord unless the company accepts the compliance
obligations. Use it as a design reference.

### Meetily

Repository: https://github.com/Zackriya-Solutions/meetily

License: MIT

What it provides:

- Local-first meeting assistant for macOS/Windows/Linux.
- Real-time transcription, summaries, and local processing.
- Tauri app with Rust backend and Next.js frontend.
- Hardware acceleration and local AI components.

Why it matters:

It is the best PC desktop-app reference if SoloRecord later needs to capture PC
microphone plus system audio from online meetings. It also shows a good shape
for a desktop companion: native capture + local/backend processing + web-style
UI.

Recommended use:

- Do not block the first internal deployment on a desktop client unless PC audio
  capture is a hard requirement.
- Build Web first for review/edit/export/admin/APK download.
- Add a Tauri desktop companion later only for PC meeting capture.

### Memoant / Minutes / HushNote / Notter

References:

- https://memoant.com/
- https://www.useminutes.app/
- https://hushnote.dev/
- https://thehomelab.dev/projects/notter

What they show:

- Local transcription plus diarization plus Ollama-style summarization is a
  validated product pattern.
- Plain-file exports, speaker labeling, and "ask your meetings" search/chat are
  common differentiators.
- Desktop capture is useful when meetings happen in Zoom, Teams, Feishu, or
  browser calls on PC.

Recommended use:

- Use as UX references for speaker labels, action items, and exports.
- Keep SoloRecord's source of truth on the server so mobile and web stay synced.

### android-vad

Repository: https://github.com/gkonovalov/android-vad

License: MIT

What it provides:

- Android offline VAD.
- WebRTC VAD, Silero VAD, and YamNet variants.
- JitPack integration.

Why it matters:

It can help if we want lightweight on-device speech/silence detection, such as
showing a live speech indicator, trimming obvious silence before upload, or
recovering from recording gaps.

Recommended use:

- Do not make it mandatory in phase 1.
- Use server-side VAD as the source of truth.
- Add Android VAD only for UX/diagnostics or network-saving optimizations.

### Android-Wave-Recorder

Repository: https://github.com/squti/Android-Wave-Recorder

License: MIT

What it provides:

- Kotlin WAV recorder.
- Memory-efficient recording.
- Configurable options and silence detection.

Why it matters:

It is useful if the local ASR model strongly prefers WAV/PCM and we decide to
record PCM directly on the phone.

Recommended use:

- Keep current M4A/AAC recording for storage efficiency unless ASR quality or
  server normalization cost says otherwise.
- Prefer server-side conversion to WAV/PCM.

### Listen

Repository: https://github.com/151henry151/listen

License: GPL-3.0

What it provides:

- Android foreground background-recording service.
- Segment rotation.
- Room metadata database.
- WorkManager scheduling.
- Service health monitoring and restart handling.
- Playback for segments.

Why it matters:

It is architecturally close to our Recording tab. The useful pattern is:
foreground service -> segment manager -> local database -> playback UI ->
storage cleanup -> health monitor.

Reuse caution:

Because it is GPL-3.0, do not copy source code into SoloRecord unless we are
willing to make the combined app GPL-compatible. Use it as a reference only.

### Millet / Meetscribe

Repository: https://github.com/pretyflaco/millet

License: GPL-3.0

What it provides:

- Local meeting transcription.
- WhisperX transcription.
- wav2vec2 alignment.
- pyannote diarization.
- Local/cloud LLM summary fallback.
- Structured outputs and PDF.
- Speaker voiceprint recognition.

Why it matters:

It is a good reference for the back-end pipeline and output artifacts, but it is
desktop/Linux oriented and GPL-3.0.

Recommended use:

- Borrow architecture ideas only.
- Useful ideas: split capture/transcribe/diarize/summarize stages, persist rich
  metadata, support multiple output formats, preserve backend/model metadata.

### ownscribe

Repository: https://github.com/paberr/ownscribe

License: MIT

What it provides:

- Local-first meeting transcription and summarization CLI.
- WhisperX.
- Optional pyannote diarization.
- Local LLM summarization with Phi/Ollama/LM Studio/OpenAI-compatible servers.
- Pipeline progress model.
- "Ask your meetings" search/chat concept.

Why it matters:

It is a cleaner license reference for meeting-level workflow and summarization
UX. It is macOS oriented, but the pipeline state model is useful.

Recommended use:

- Reference its progress stages and summary-template strategy.
- Do not depend on its capture layer.

### HushNote

Repository: https://github.com/peteonrails/hushnote

License: MIT

What it provides:

- Local recording, Whisper transcription, diarization, and Ollama summaries.
- Multiple transcript formats.
- Interactive speaker labeling.

Why it matters:

It validates the same product shape: local meeting audio -> local ASR ->
speaker attribution -> local LLM summary.

Recommended use:

- Reference speaker-labeling UX and output formats.
- Keep our own mobile/gateway architecture.

### OpenWhispr diarization architecture

Article: https://openwhispr.com/blog/local-speaker-diarization

What it provides:

- A practical local diarization breakdown:
  VAD -> segmentation -> speaker embeddings -> clustering -> profile matching.
- Uses sherpa-onnx as the native ONNX runtime.
- Stores voice fingerprints locally.
- Calls out real limitations such as overlap, noisy rooms, and cold-start
  speaker identity.

Why it matters:

This supports our decision to make diarization an independent stage, keep
anonymous speaker IDs first, and map them to names later.

Recommended use:

- Adopt the same conceptual stages.
- Store speaker embeddings locally on the gateway only if product policy allows
  speaker memory.
- Always make speaker names editable or correctable.

## Architecture lessons

1. Do not couple recording and ASR.
   Recording must remain reliable even when models are slow or unavailable.

2. Use rolling audio files on Android.
   Similar Android recorders use foreground services, segment managers, local
   metadata databases, and recovery from mic interruptions.

3. Use the gateway as the processing owner.
   It can run heavier models, normalize audio, retry per segment, and keep model
   credentials out of the APK.

4. Keep VAD, diarization, ASR, and summary as separate jobs.
   This gives us retry boundaries and lets us compare models stage by stage.

5. Treat diarization as probabilistic.
   Store anonymous speaker IDs, confidence, and correction state. Do not pretend
   the system always knows the real person.

6. Prefer permissive licenses for code reuse.
   Apache-2.0 and MIT are straightforward. GPL-3.0 projects are useful for
   design reference, but direct code reuse affects the whole app license.

## Proposed SoloRecord component choices

### APK

- Keep native Android Java/Kotlin app code owned by us.
- Implement foreground `RecordingService`.
- Store meeting and segment metadata locally.
- Use WorkManager for upload retries.
- Use MediaRecorder M4A/AAC initially.
- Optionally add `android-vad` later for live speech indicator or upload
  optimization.

### Local gateway / ASR service

- Start with `sherpa-onnx` for VAD + ASR experiments.
- Evaluate SenseVoice/Paraformer/Whisper models through sherpa-onnx for Chinese
  meeting audio.
- Add sherpa-onnx diarization when action-owner attribution must be trusted.
- Keep Vosk as a small-device fallback.
- Keep pyannote/WhisperX as benchmark tools, not necessarily production runtime,
  because Python/PyTorch deployment is heavier.

### Meeting intelligence

- Store raw chunks separately from merged transcript.
- Store processing metadata: model name, model version, runtime, timestamps,
  confidence, VAD speech ratio, diarization confidence.
- Generate summary and action items from the merged timeline.
- Let user or admin correct speaker names.

## Reuse priority

1. Reuse `sherpa-onnx` as a dependency or sidecar binary.
2. Borrow `Listen` architecture ideas for Android foreground recording and
   segment rotation, without copying GPL code.
3. Use `android-vad` only if on-device VAD is needed.
4. Use `ownscribe`/`HushNote` ideas for progress states, outputs, and speaker
   labeling.
5. Avoid directly importing GPL meeting-app code unless the license plan changes.
