import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(
    os.getenv("PROJECT_ROOT") or Path(__file__).resolve().parents[3]
).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "投标文件自动脱敏服务"
    env: str = "dev"
    # 本地部署默认单用户全权限；服务器部署可关闭，恢复管理员角色校验
    local_full_access: bool = True
    # 由 scripts/run-server.ps1 启动时设为 true，用于开放“重启服务”
    app_supervised: bool = False

    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'app.db').as_posix()}"
    secret_key: str = "dev-only"
    data_dir: Path = PROJECT_ROOT / "data"

    mineru_provider: str = "official"
    mineru_api_token: str = ""
    mineru_api_base: str = "https://mineru.net/api/v4"
    mineru_model_version: str = "pipeline"
    mineru_is_ocr: bool = True
    mineru_enable_table: bool = True
    mineru_enable_formula: bool = False
    mineru_language: str = "ch"
    mineru_split_pages: int = 200
    mineru_split_mb: int = 200
    mineru_keep_images: bool = False
    mineru_max_daily_pages: int = 1000
    mineru_poll_interval: int = 10
    mineru_timeout: int = 1800

    face_detection_enabled: bool = False
    face_model_path: Path = PROJECT_ROOT / "data" / "models" / "insightface" / "det_10g.onnx"
    face_detect_dpi: int = 150
    face_det_size: int = 640
    face_det_thresh: float = 0.5
    face_min_size_pt: float = 18.0
    face_pad_ratio: float = 0.12
    face_tile_size: int = 0
    face_scan_mode: str = "image_pages"
    face_replace_id_avatar: bool = True
    face_fail_policy: str = "fail"
    face_ctx_id: int = -1
    face_ort_threads: int = 0

    blue_stamp_enabled: bool = True
    blue_stamp_dpi: int = 150

    social_insurance_enabled: bool = True
    social_insurance_dpi: int = 200

    admin_username: str = "admin"
    admin_password: str = "admin123"

    worker_enabled: bool = True
    max_upload_mb: int = 200
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @field_validator("data_dir", mode="after")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    def ensure_dirs(self) -> None:
        for sub in ("original", "redacted", "mineru", "faces", "models", "logs"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()