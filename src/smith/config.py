from pydantic import Field
from pydantic_settings import BaseSettings


class SmithConfig(BaseSettings):
    """
    Application-wide configuration.
    Reads from environment variables (e.g., SMITH_TIMEOUT=60).
    """

    # Execution constraints
    default_timeout: float = Field(default=45.0, alias="SMITH_TIMEOUT")
    max_retries: int = Field(default=2, alias="SMITH_MAX_RETRIES")
    trace_limit_chars: int = Field(default=50_000, alias="SMITH_TRACE_LIMIT")

    # Safety
    require_approval: bool = Field(default=True, alias="SMITH_REQUIRE_APPROVAL")

    # LLM Configuration
    primary_model: str = Field(default="gemini-2.5-flash", alias="SMITH_LLM_MODEL")
    fallback_models: list[str] = ["gemini-1.5-pro"]

    # Environment
    debug_mode: bool = Field(default=False, alias="SMITH_DEBUG")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


config = SmithConfig()
