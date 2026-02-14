from pydantic import Field
from pydantic_settings import BaseSettings


class SmithConfig(BaseSettings):
    """
    Application-wide configuration.
    Reads from environment variables (e.g., SMITH_TIMEOUT=60).
    """

    # Execution constraints - OPTIMIZED
    default_timeout: float = Field(
        default=30.0, alias="SMITH_TIMEOUT"
    )  # Reduced from 45s
    max_retries: int = Field(default=2, alias="SMITH_MAX_RETRIES")
    trace_limit_chars: int = Field(default=50_000, alias="SMITH_TRACE_LIMIT")

    # Safety
    require_approval: bool = Field(default=True, alias="SMITH_REQUIRE_APPROVAL")

    # LLM Configuration - GROQ ONLY
    primary_model: str = Field(
        default="llama-3.3-70b-versatile", alias="SMITH_LLM_MODEL"
    )
    fallback_models: list[str] = ["llama3-70b-8192", "mixtral-8x7b-32768"]

    # Concurrency
    max_workers: int = Field(default=10, alias="SMITH_MAX_WORKERS")
    max_concurrent_traces: int = Field(default=4, alias="SMITH_MAX_CONCURRENT_TRACES")

    # Rate Limiting
    groq_rpm: int = Field(default=30, alias="SMITH_GROQ_RPM")
    groq_tpm: int = Field(default=40000, alias="SMITH_GROQ_TPM")

    # Resilience - FASTER RECOVERY
    llm_max_retries: int = Field(
        default=3, alias="SMITH_LLM_MAX_RETRIES"
    )  # Reduced from 5
    backoff_max_seconds: float = Field(
        default=30.0, alias="SMITH_BACKOFF_MAX_SECONDS"
    )  # Halved from 60s

    # Environment
    debug_mode: bool = Field(default=False, alias="SMITH_DEBUG")

    # Sub-Agents and Fleet Mode
    max_subagent_depth: int = Field(default=3, alias="SMITH_MAX_SUBAGENT_DEPTH")
    max_fleet_size: int = Field(default=5, alias="SMITH_MAX_FLEET_SIZE")
    tool_lock_timeout: float = Field(default=30.0, alias="SMITH_TOOL_LOCK_TIMEOUT")
    enable_subagents: bool = Field(default=True, alias="SMITH_ENABLE_SUBAGENTS")
    enable_fleet_mode: bool = Field(default=True, alias="SMITH_ENABLE_FLEET_MODE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


config = SmithConfig()
