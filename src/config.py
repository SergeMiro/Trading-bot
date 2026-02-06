from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database (Supabase PostgreSQL)
    database_url: str = "postgresql://postgres:password@localhost:5432/postgres"

    # LLM (MiniMax via Chutes.ai — OpenAI-compatible)
    llm_api_key: str = ""
    llm_base_url: str = "https://llm.chutes.ai/v1"
    llm_model: str = "openai/MiniMaxAI/MiniMax-M2.1-TEE"

    # SEC EDGAR
    sec_user_agent: str = "TradingBot bot@example.com"

    # IBKR
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1

    # Trading settings
    min_market_cap: int = 500_000_000
    max_monitoring_lines: int = 100
    score_threshold_buy: int = 70
    score_threshold_hold: int = 50
    target_gain: float = 0.08
    stop_loss: float = 0.05
    max_hold_days: int = 7
    risk_per_trade: float = 0.02

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
