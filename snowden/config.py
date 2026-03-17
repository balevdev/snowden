"""
snowden/config.py

All settings loaded from environment variables via Pydantic Settings.
No YAML, no TOML. Docker Compose sets env vars for infra.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    # Database
    tsdb_host: str = "localhost"
    tsdb_port: int = 5432
    tsdb_user: str = "snowden"
    tsdb_password: str = "snowden_dev"
    tsdb_db: str = "snowden"

    # Polymarket
    poly_clob_host: str = "https://clob.polymarket.com"
    poly_gamma_host: str = "https://gamma-api.polymarket.com"
    poly_data_host: str = "https://data-api.polymarket.com"
    poly_ws_host: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    poly_api_key: str = ""
    poly_api_secret: str = ""
    poly_api_passphrase: str = ""
    poly_funder: str = ""
    poly_private_key: str = ""

    # Claude
    anthropic_api_key: str = ""

    # System
    mode: str = "paper"
    bankroll: float = 2000.0
    cycle_interval: int = 900
    sentinel_interval: int = 60

    # Risk
    max_heat: float = 0.80
    max_single_position: float = 0.25
    max_daily_drawdown: float = 0.10
    max_correlated: float = 0.40
    kelly_divisor: float = 4.0
    edge_threshold: float = 0.05
    min_trade_usd: float = 5.0

    # Scanner
    min_liquidity_usd: float = 5000.0
    min_book_depth_usd: float = 500.0
    max_spread: float = 0.08
    min_hours_to_resolve: float = 24.0
    max_days_to_resolve: float = 180.0
    efficiency_score_cutoff: float = 0.4

    # Scanner strategy thresholds
    theta_boundary: float = 0.88
    longshot_boundary: float = 0.08
    stale_vol_threshold: float = 20_000.0
    stale_spread_threshold: float = 0.03
    partisan_mid_low: float = 0.25
    partisan_mid_high: float = 0.75
    scanner_result_limit: int = 30

    # Kelly
    kelly_edge_threshold: float = 0.03
    slippage_buffer: float = 0.01
    slippage_multiplier: float = 1.03

    # Analyst
    analyst_model: str = "claude-opus-4-6-20250415"
    analyst_max_tokens: int = 800
    triage_model: str = "claude-haiku-4-5-20251001"

    # Calibration
    calibration_min_samples: int = 50
    calibration_min_report: int = 20
    calibration_clip_low: float = 0.001
    calibration_clip_high: float = 0.999

    # Chief
    min_confidence: float = 0.3
    max_position_hold_hours: float = 720.0
    stop_loss_pct: float = 0.30

    # Rate limiting
    poly_max_concurrent: int = 5
    poly_request_delay: float = 0.1

    # Discord
    discord_webhook_url: str = ""
    discord_channel_id: str = ""

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def tsdb_dsn(self) -> str:
        return f"postgresql://{self.tsdb_user}:{self.tsdb_password}@{self.tsdb_host}:{self.tsdb_port}/{self.tsdb_db}"

    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"


settings = Settings()
