from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_dsn: str = "postgresql://forge:forge@postgres:5432/forge"
    redis_url: str = "redis://redis:6379/0"
    llm_mode: str = "mock"
    anthropic_api_key: str | None = None
    claude_model: str = "claude-3-5-haiku-latest"
    claude_max_tokens: int = 800

    class Config:
        env_file = ".env"


settings = Settings()
