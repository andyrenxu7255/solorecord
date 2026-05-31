from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SOLO_",
        env_file=(".env", "server/.env"),
        extra="ignore",
    )

    app_name: str = "SoloRecord"
    base_url: str = "http://127.0.0.1:8000"
    secret_key: str = Field(default="change-me-before-production")
    data_dir: Path = Path("var")
    database_path: Path = Path("var/solorecord.db")
    storage_dir: Path = Path("var/storage")
    apk_dir: Path = Path("var/apk")
    static_dir: Path = Path("server/static")
    allow_demo_login: bool = True
    access_token_minutes: int = 720

    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_bind_dn_template: str = ""
    ldap_lookup_bind_dn: str = ""
    ldap_lookup_bind_password: str = ""
    ldap_search_dn: str = ""
    ldap_search_filter: str = "({username_key}={username})"
    ldap_username_key: str = "cn"
    ldap_email_key: str = "mail"
    ldap_email_postfix: str = ""
    ldap_display_name_key: str = "displayName"
    ldap_tls_validate: bool = True
    ldap_admin_group_dn: str = ""
    ldap_admin_users: str = ""
    ldap_default_role: str = "user"
    ldap_timeout_seconds: int = 10

    sso_verify_mode: str = "demo"
    sso_issuer: str = ""
    sso_client_id: str = ""
    sso_client_secret: str = ""
    sso_redirect_uri: str = ""
    sso_scope: str = "openid email"
    sso_authorize_url: str = ""
    sso_token_url: str = ""
    sso_userinfo_url: str = ""
    sso_jwks_url: str = ""
    sso_introspection_url: str = ""
    sso_ticket_verify_url: str = ""

    asr_provider: str = "mock"
    asr_command: str = ""
    asr_endpoint: str = ""
    asr_api_key: str = ""
    asr_model: str = ""
    asr_timeout_seconds: int = 3600
    audio_segment_minutes: int = 5
    target_sample_rate: int = 16000
    enable_diarization: bool = True
    enable_denoise: bool = False
    enable_semantic_segmentation: bool = True

    llm_provider: str = "mock"
    llm_endpoint: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    hermes_webhook_url: str = ""
    hermes_webhook_token: str = ""

    es_enabled: bool = False
    es_url: str = ""
    es_index: str = "solorecord_meetings"
    es_api_key: str = ""
    es_username: str = ""
    es_password: str = ""
    external_api_tokens: str = ""

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.apk_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
