"""
Centralized app configuration, loaded from environment variables (.env).
Nothing else in the app should read os.environ directly — import `settings` from here.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_key: str

    # OpenRouter
    openrouter_api_key: str
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    openrouter_fallback_models: str = "inclusionai/ling-3.0-flash:free, openai/gpt-oss-20b:free"  # comma-separated, tried in order if the primary fails
    openrouter_vision_model: str = ""
    openrouter_vision_fallback_models: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # App
    max_upload_mb: int = 20
    allowed_origins: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def openrouter_models_chain(self) -> list[str]:
        """Primary model first, then fallbacks in order."""
        fallbacks = [m.strip() for m in self.openrouter_fallback_models.split(",") if m.strip()]
        return [self.openrouter_model] + fallbacks

    @property
    def openrouter_vision_models_chain(self) -> list[str]:
        primary = [self.openrouter_vision_model.strip()] if self.openrouter_vision_model.strip() else []
        fallbacks = [m.strip() for m in self.openrouter_vision_fallback_models.split(",") if m.strip()]
        return primary + fallbacks


settings = Settings()
