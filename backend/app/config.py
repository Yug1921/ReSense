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

    # OpenRouter
    openrouter_api_key: str
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    openrouter_fallback_models: str = "inclusionai/ling-3.0-flash:free, google/gemma-4-26b-a4b-it:free"  # comma-separated, tried in order if the primary fails
    openrouter_vision_model: str = ""
    openrouter_vision_fallback_models: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    groq_api_key: str = Field(default="", validation_alias="Groq")
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = Field(default="", validation_alias="Gemini")
    gemini_model: str = "gemini-3.8-flash"

    # App
    max_upload_mb: int = 20
    allowed_origins: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        configured = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        local_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
        return list(dict.fromkeys(configured + local_origins))

    @property
    def openrouter_models_chain(self) -> list[str]:
        """Primary model first, then fallbacks in order."""
        fallbacks = [m.strip() for m in self.openrouter_fallback_models.split(",") if m.strip()]
        return [self.openrouter_model] + fallbacks

    @property
    def provider_chain(self) -> list[dict]:
        chain = [
            {
                "base_url": self.openrouter_base_url,
                "api_key": self.openrouter_api_key,
                "model": model,
            }
            for model in self.openrouter_models_chain
        ]
        if self.groq_api_key:
            chain.append({
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": self.groq_api_key,
                "model": self.groq_model,
            })
        if self.gemini_api_key:
            chain.append({
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "api_key": self.gemini_api_key,
                "model": self.gemini_model,
            })
        return chain

    @property
    def openrouter_vision_models_chain(self) -> list[str]:
        primary = [self.openrouter_vision_model.strip()] if self.openrouter_vision_model.strip() else []
        fallbacks = [m.strip() for m in self.openrouter_vision_fallback_models.split(",") if m.strip()]
        return primary + fallbacks


settings = Settings()
