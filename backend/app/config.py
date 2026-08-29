from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    app_name: str = "Failure Forensics Tool"
    database_url: str = "sqlite:///./data/forensics.db"
    data_dir: Path = Path("./data")
    uploads_dir: Path = Path("./data/uploads")
    samples_dir: Path = Path("../samples")
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if v is None or v == "":
            return [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ]
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [p.strip() for p in s.split(",") if p.strip()]
        return v


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
