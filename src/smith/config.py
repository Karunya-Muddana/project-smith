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

    # LLM Configuration - OpenRouter
    primary_model: str = Field(
        default="meta/llama-4-maverick-17b-128e-instruct", alias="SMITH_LLM_MODEL"
    )
    # Fallbacks must differ from primary_model to provide real failover.
    fallback_models: list[str] = Field(
        default_factory=lambda: [
            "meta/llama-4-scout-17b-16e-instruct",
            "meta/llama-3.3-70b-instruct",
        ],
        alias="SMITH_FALLBACK_MODELS",
    )

    # Synthesis Router: model variants
    synthesis_heavy_model: str = Field(
        default="meta/llama-4-maverick-17b-128e-instruct", alias="SMITH_SYNTHESIS_HEAVY_MODEL"
    )
    synthesis_fast_model: str = Field(
        default="meta/llama-4-maverick-17b-128e-instruct", alias="SMITH_SYNTHESIS_FAST_MODEL"
    )

    # Concurrency
    max_workers: int = Field(default=10, alias="SMITH_MAX_WORKERS")
    max_concurrent_traces: int = Field(default=4, alias="SMITH_MAX_CONCURRENT_TRACES")

    # Rate Limiting (generic)
    api_rpm: int = Field(default=30, alias="SMITH_API_RPM")
    api_tpm: int = Field(default=100000, alias="SMITH_API_TPM")

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

    # Run Cache / Warm Start
    cache_enabled: bool = Field(default=True, alias="SMITH_CACHE_ENABLED")
    cache_ttl_seconds: int = Field(default=3600, alias="SMITH_CACHE_TTL")
    cache_dir: str = Field(default="~/.smith_cache", alias="SMITH_CACHE_DIR")

    # Long-term Memory / RAG
    memory_enabled: bool = Field(default=True, alias="SMITH_MEMORY_ENABLED")
    memory_dir: str = Field(default="~/.smith_memory", alias="SMITH_MEMORY_DIR")
    memory_top_k: int = Field(default=3, alias="SMITH_MEMORY_TOP_K")
    memory_max_records: int = Field(default=500, alias="SMITH_MEMORY_MAX_RECORDS")
    memory_min_score: float = Field(default=0.25, alias="SMITH_MEMORY_MIN_SCORE")
    memory_summarize_batch: int = Field(default=20, alias="SMITH_MEMORY_SUMMARIZE_BATCH")
    memory_inject_max_chars: int = Field(default=1500, alias="SMITH_MEMORY_INJECT_MAX_CHARS")

    # Conversational context reuse
    conversation_context_turns: int = Field(default=3, alias="SMITH_CONTEXT_TURNS")
    time_sensitive_fresh_seconds: int = Field(default=300, alias="SMITH_TIME_SENSITIVE_FRESH_SECONDS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


config = SmithConfig()
