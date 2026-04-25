from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["auto", "anthropic", "gemini"]

ANTHROPIC_MODELS = {
    "strategist": "claude-opus-4-6",
    "player": "claude-sonnet-4-6",
    "builder": "claude-sonnet-4-6",
}
GEMINI_MODELS = {
    "strategist": "gemini-3-flash-preview",
    "player": "gemini-3-flash-preview",
    "builder": "gemini-3-flash-preview",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    llm_provider: Provider = "auto"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    google_api_key: str = ""

    strategist_model: str = ""
    player_model: str = ""
    builder_model: str = ""
    llm_max_concurrency: int = 0

    database_url: str = "sqlite:///./cubist.db"

    time_per_move_ms: int = 20_000
    games_per_pairing: int = 2
    max_moves_per_game: int = 120

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    @property
    def resolved_llm_provider(self) -> Literal["anthropic", "gemini"]:
        if self.llm_provider != "auto":
            return self.llm_provider
        if (self.gemini_api_key or self.google_api_key) and not self.anthropic_api_key:
            return "gemini"
        return "anthropic"

    @property
    def resolved_llm_max_concurrency(self) -> int:
        if self.llm_max_concurrency > 0:
            return self.llm_max_concurrency
        return 2 if self.resolved_llm_provider == "gemini" else 30

    @model_validator(mode="after")
    def set_default_models(self) -> "Settings":
        defaults = GEMINI_MODELS if self.resolved_llm_provider == "gemini" else ANTHROPIC_MODELS
        if not self.strategist_model:
            self.strategist_model = defaults["strategist"]
        if not self.player_model:
            self.player_model = defaults["player"]
        if not self.builder_model:
            self.builder_model = defaults["builder"]
        return self


settings = Settings()
