from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ENV_FILE = Path(__file__).with_name(".env")
WORKING_DIR_ENV_FILE = Path(".env")


class Settings(BaseSettings):
    app_name: str = "InterviewOS AI"
    app_env: str = "development"
    secret_key: str = "development_secret_key_change_me_32_chars"
    frontend_url: str = "http://localhost:3000"
    allow_dev_auth_fallback: bool = True

    database_url: str | None = None
    database_url_sync: str | None = None

    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    dsa_gemini_api_key: str | None = None
    dsa_groq_api_key: str | None = None
    aptitude_gemini_api_key: str | None = None
    aptitude_groq_api_key: str | None = None
    technical_gemini_api_key: str | None = None
    technical_groq_api_key: str | None = None
    hr_gemini_api_key: str | None = None
    hr_groq_api_key: str | None = None
    report_gemini_api_key: str | None = None
    report_groq_api_key: str | None = None
    roadmap_gemini_api_key: str | None = None
    roadmap_groq_api_key: str | None = None
    resume_gemini_api_key: str | None = None
    resume_groq_api_key: str | None = None
    bot_gemini_api_key: str | None = None
    bot_groq_api_key: str | None = None
    planning_gemini_api_key: str | None = None
    planning_groq_api_key: str | None = None
    memory_gemini_api_key: str | None = None
    memory_groq_api_key: str | None = None
    reviewer_gemini_api_key: str | None = None
    reviewer_groq_api_key: str | None = None
    practice_gemini_api_key: str | None = None
    practice_groq_api_key: str | None = None
    evaluation_gemini_api_key: str | None = None
    evaluation_groq_api_key: str | None = None
    llm_live_call_timeout_seconds: float = 8.0
    llm_legacy_call_timeout_seconds: float = 8.0
    llm_provider_order: str = "groq,gemini"
    llm_prompt_cache_enabled: bool = True
    llm_prompt_cache_ttl_seconds: int = 1800
    llm_max_input_tokens_default: int = 12000
    llm_max_input_tokens_hr: int = 4500
    llm_max_input_tokens_aptitude: int = 3500
    llm_max_input_tokens_dsa: int = 5500
    llm_max_input_tokens_technical: int = 6500
    llm_max_input_tokens_planning: int = 7000
    llm_max_input_tokens_evaluation: int = 6500
    llm_max_input_tokens_report: int = 9000
    llm_max_input_tokens_roadmap: int = 7000
    llm_max_input_tokens_resume: int = 7000
    llm_max_input_tokens_bot: int = 5500
    llm_max_input_tokens_reviewer: int = 6000
    llm_max_input_tokens_memory: int = 5000
    llm_max_input_tokens_practice: int = 6000
    llm_provider_quota_cooldown_seconds: int = 30
    llm_provider_context_cooldown_seconds: int = 60
    llm_provider_error_cooldown_seconds: int = 30
    llm_provider_max_cooldown_seconds: int = 900
    llm_provider_failure_threshold: int = 2
    llm_provider_quota_global_cooldown_enabled: bool = True
    llm_max_gemini_concurrent_requests: int = 1
    llm_max_groq_concurrent_requests: int = 2
    llm_evaluation_cache_ttl_seconds: int = 3600
    live_round_llm_evaluation_enabled: bool = False

    judge0_base_url: str = "http://127.0.0.1:2358"
    judge0_api_key: str | None = None
    judge0_auth_header: str = "X-Auth-Token"
    judge0_rapidapi_host: str | None = None
    judge0_timeout_seconds: int = 8
    enable_local_code_runner: bool = True
    prefer_local_code_runner: bool = True
    local_code_runner_compile_timeout_seconds: int = 10
    local_code_runner_timeout_seconds: int = 3
    code_execution_backend: str = "internal"
    code_execution_workspace_dir: str = "./data/code_execution"
    code_execution_max_source_bytes: int = 262144
    code_execution_max_output_bytes: int = 65536
    code_execution_compile_timeout_seconds: int = 30
    code_execution_run_timeout_seconds: int = 5
    code_execution_memory_limit_mb: int = 1024

    chroma_persist_dir: str = "./chroma_db"
    upload_dir: str = "./uploads"
    resume_file_retention_hours: int = 24
    resume_file_cleanup_interval_seconds: int = 3600
    dev_store_path: str = "./data/development_store.json"
    dev_store_compact_json: bool = True
    max_file_size_mb: int = 10

    redis_url: str = "redis://localhost:6379/0"
    workflow_queue_backend: str = "inprocess"
    workflow_queue_name: str = "interviewos:workflow:jobs"
    workflow_async_generation: bool = False
    workflow_job_max_attempts: int = 3
    workflow_retry_base_seconds: float = 2.0
    workflow_enqueue_timeout_seconds: float = 2.0
    workflow_generation_timeout_seconds: float = 420.0
    workflow_redis_brpop_timeout_seconds: int = 5
    workflow_worker_heartbeat_seconds: float = 5.0
    workflow_queue_pickup_grace_seconds: float = 20.0
    workflow_queue_visibility_timeout_seconds: float = 120.0
    workflow_recover_stalled_redis_jobs_in_api: bool = False
    workflow_graph_node_timeout_seconds: float = 120.0
    agent_section_generation_timeout_seconds: float = 90.0

    livekit_url: str | None = None
    livekit_api_key: str | None = None
    livekit_api_secret: str | None = None
    livekit_token_ttl_seconds: int = 3600

    deepgram_api_key: str | None = None
    deepgram_model: str = "nova-3"
    deepgram_language: str = "en-US"
    deepgram_endpointing_ms: int = 800
    deepgram_utterance_end_ms: int = 1000

    postgres_persistence_enabled: bool = False
    postgres_persistence_strict: bool = False
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 10
    postgres_connect_timeout_seconds: int = 5
    postgres_statement_timeout_ms: int = 8000
    migrations_dir: str = "./migrations"
    semantic_memory_backend: str = "chroma"
    semantic_memory_query_cache_ttl_seconds: int = 45
    semantic_embedding_provider: str = "sentence-transformers"
    gemini_embedding_model: str = "models/gemini-embedding-001"
    sentence_transformer_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    sentence_transformer_local_files_only: bool = True
    semantic_memory_deferred_flush_delay_seconds: float = 0.1
    semantic_memory_batch_flush_size: int = 16
    agentic_tool_call_timeout_seconds: float = 1.2
    agentic_tool_call_total_timeout_seconds: float = 4.0
    qualitative_review_mode: str = "sampled"
    enable_afc: bool = False
    max_remote_calls: int = 1
    agentic_native_tool_call_enabled: bool = False
    max_react_iterations: int = 1
    max_react_tool_calls_per_iteration: int = 1
    max_react_total_tool_calls: int = 1
    workflow_generation_profile: str = "fast"
    agent_generation_max_concurrent_sections: int = 2
    langgraph_generation_recursion_limit: int = 40
    langgraph_lifecycle_recursion_limit: int = 40
    langgraph_max_generation_attempts: int = 2
    langgraph_max_debate_rounds: int = 2
    langgraph_max_orchestrator_replans: int = 1
    langgraph_max_lifecycle_review_attempts: int = 2
    planning_agent_live_timeout_seconds: float = 6.0
    security_llm_classifier_enabled: bool = False
    security_llm_classifier_fail_closed: bool = False
    langgraph_human_interrupts_enabled: bool = False
    langgraph_generation_interrupt_before: str = ""
    langgraph_generation_interrupt_after: str = ""
    langgraph_lifecycle_interrupt_before: str = ""
    langgraph_lifecycle_interrupt_after: str = ""

    jwt_secret: str = "development_jwt_secret_change_me_32_chars"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    model_config = SettingsConfigDict(
        env_file=(BACKEND_ENV_FILE, WORKING_DIR_ENV_FILE),
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
