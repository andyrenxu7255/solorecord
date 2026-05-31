import json

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    display_name: str = Field(default="Demo User")
    email: str = Field(default="demo@example.com")


class LdapLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class MeetingCreate(BaseModel):
    title: str = ""
    started_at: str | None = None
    join_code: str = ""
    recording_mode: str = "single"
    max_sources: int = 1
    source_label: str = ""


class RecordingSourceCreate(BaseModel):
    source_id: str = ""
    label: str = ""
    device_name: str = ""


class MultiSourceJoinRequest(BaseModel):
    title: str = ""
    join_code: str = ""
    source_label: str = ""
    device_name: str = ""


class MeetingUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    role_notes: str | None = None


class SpeakerRename(BaseModel):
    speaker_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    replace_text: bool = False


class TranscriptSegmentIn(BaseModel):
    id: str | None = None
    source_id: str = ""
    speaker_id: str = "SPEAKER_01"
    display_name: str = "发言人 1"
    source_segment_no: int | None = None
    start_ms: int = 0
    end_ms: int = 0
    text: str
    confidence: float | None = None
    flags: list[str] = Field(default_factory=list)

    @field_validator("flags", mode="before")
    @classmethod
    def normalize_flags(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return [value]
            return parsed if isinstance(parsed, list) else [str(parsed)]
        return value


class TranscriptUpdate(BaseModel):
    version: int
    segments: list[TranscriptSegmentIn]


class ActionItemIn(BaseModel):
    owner: str = ""
    task: str
    due: str = ""
    status: str = "open"


class ActionItemsUpdate(BaseModel):
    items: list[ActionItemIn] = Field(default_factory=list)


class ProviderConfig(BaseModel):
    asr_provider: str = "mock"
    asr_command: str = ""
    asr_endpoint: str = ""
    asr_api_key: str = ""
    asr_model: str = ""
    llm_provider: str = "mock"
    llm_endpoint: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    hermes_webhook_url: str = ""
    hermes_webhook_token: str = ""
    es_enabled: bool = False
    es_url: str = ""
    es_index: str = "solorecord_meetings"
    external_api_tokens: str = ""
    audio_segment_minutes: int = 5
    enable_diarization: bool = True
    enable_denoise: bool = False
    target_sample_rate: int = 16000
    enable_semantic_segmentation: bool = True


class SegmentJsonUpload(BaseModel):
    segment_no: int
    source_id: str = ""
    source_label: str = ""
    source_segment_no: int | None = None
    file_name: str
    audio_base64: str
    start_ms: int = 0
    end_ms: int = 0
    duration_ms: int = 0
