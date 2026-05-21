from pydantic_settings import BaseSettings
from pydantic import Field


class OracleSettings(BaseSettings):
    host: str = Field("", alias="ORACLE_HOST")
    client_id: str = Field("", alias="ORACLE_CLIENT_ID")
    client_secret: str = Field("", alias="ORACLE_CLIENT_SECRET")
    token_url: str = Field("", alias="ORACLE_TOKEN_URL")
    ledger_id: int = Field(1001, alias="ORACLE_LEDGER_ID")
    period_name: str = Field("Jan-25", alias="ORACLE_PERIOD_NAME")

    model_config = {"env_file": ".env", "extra": "ignore"}


class AgentSettings(BaseSettings):
    provider: str = Field("claude", alias="LLM_PROVIDER")
    max_iterations: int = Field(30, alias="AGENT_MAX_ITERATIONS")
    variance_threshold_pct: float = Field(10.0, alias="AGENT_VARIANCE_THRESHOLD_PCT")
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o", alias="OPENAI_MODEL")

    model_config = {"env_file": ".env", "extra": "ignore"}


class NotificationSettings(BaseSettings):
    controller_email: str = Field("controller@example.com", alias="NOTIFICATION_CONTROLLER_EMAIL")
    smtp_host: str = Field("localhost", alias="NOTIFICATION_SMTP_HOST")
    smtp_port: int = Field(587, alias="NOTIFICATION_SMTP_PORT")
    from_email: str = Field("erp-agent@example.com", alias="NOTIFICATION_FROM_EMAIL")

    model_config = {"env_file": ".env", "extra": "ignore"}
