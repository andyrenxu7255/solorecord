from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    display_name: str = Field(default="Demo User")
    email: str = Field(default="demo@example.com")


class MeetingCreate(BaseModel):
    title: str = ""
    started_at: str | None = None


class MeetingUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    role_notes: str | None = None


class SpeakerRename(BaseModel):
    speaker_id: str
    display_name: str


class TranscriptSegmentIn(BaseModel):
    id: str | None = None
    speaker_id: str = "SPEAKER_01"
    display_name: str = "发言人 1"
    start_ms: int = 0
    end_ms: int = 0
    text: str
    confidence: float | None = None
    flags: list[str] = Field(default_factory=list)


class TranscriptUpdate(BaseModel):
    version: int
    segments: list[TranscriptSegmentIn]


class ActionItemIn(BaseModel):
    owner: str = ""
    task: str
    due: str = ""
    status: str = "open"


class ProviderConfig(BaseModel):
    asr_provider: str = "mock"
    asr_command: str = ""
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


class SegmentJsonUpload(BaseModel):
    segment_no: int
    file_name: str
    audio_base64: str
    start_ms: int = 0
    end_ms: int = 0
    duration_ms: int = 0
