"""
Centralized app configuration, loaded from environment variables (.env).
Nothing else in the app should read os.environ directly — import `settings` from here.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_key: str

    # Free AI providers. Any of the three keys is enough; with all three the app
    # falls back from one to the next. Models are picked automatically from what
    # each key can use (see services/providers.py). The *_MODEL settings are
    # optional: models named there are tried first, comma-separated.
    gemini_api_key: str = Field(default="", validation_alias="Gemini")
    gemini_model: str = ""
    groq_api_key: str = Field(default="", validation_alias="Groq")
    groq_model: str = ""
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_fallback_models: str = ""
    openrouter_vision_model: str = ""
    openrouter_vision_fallback_models: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # App
    max_upload_mb: int = 20
    allowed_origins: str = "http://localhost:3000"
    crossref_mailto: str = ""
    openalex_api_key: str = ""  # free key from openalex.org; anonymous use has a tiny daily quota

    @property
    def allowed_origins_list(self) -> list[str]:
        configured = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        local_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
        return list(dict.fromkeys(configured + local_origins))

    @property
    def openrouter_vision_models_chain(self) -> list[str]:
        primary = [self.openrouter_vision_model.strip()] if self.openrouter_vision_model.strip() else []
        fallbacks = [m.strip() for m in self.openrouter_vision_fallback_models.split(",") if m.strip()]
        return primary + fallbacks


settings = Settings()
