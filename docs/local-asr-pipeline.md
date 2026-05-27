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
- Uploads missing segments when network is stable.
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
