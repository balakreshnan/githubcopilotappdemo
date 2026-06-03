"""Application configuration loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Foundry / Azure AI connection
    project_endpoint: str = ""
    main_agent_id: str = ""
    connected_agent_ids: str = ""
    model_deployment: str = ""

    # Behavior
    use_mock: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def connected_agent_id_list(self) -> list[str]:
        return [a.strip() for a in self.connected_agent_ids.split(",") if a.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def live_ready(self) -> bool:
        """True when enough config exists to talk to a real Foundry project."""
        return bool(self.project_endpoint and self.main_agent_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
