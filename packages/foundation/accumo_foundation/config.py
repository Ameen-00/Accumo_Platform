from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "accumo"
    env: str = "dev"
    country_code: str = "IN"
    base_currency: str = "INR"
    public_host: str = "localhost"

    secret_key: str = "dev-only-not-for-production"
    account_hmac_key: str = "dev-only-hmac"
    bank_encrypt_key: str = ""

    database_url: str = "postgresql+psycopg://pulse:pulse@localhost:5432/pulse"
    session_hours: int = 12
    login_max_attempts: int = 8
    login_window_seconds: int = 300
    retention_months: int = 24
    log_customer_payloads: bool = False
    upload_dir: str = ".data/uploads"

    @property
    def cookie_secure(self) -> bool:
        return self.env != "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
