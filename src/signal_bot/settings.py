"""
Settings - Application configuration using Pydantic Settings.

All sensitive config comes from environment variables.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Required:
        TELEGRAM_BOT_TOKEN: Your Telegram bot token from @BotFather
        ENCRYPTION_SECRET: Master secret for encrypting API keys (min 16 chars)
        ADMIN_TELEGRAM_ID: Your Telegram user ID (only you can post signals)
        SIGNAL_CHANNEL_ID: The channel/group ID where you post signals
    
    Optional:
        WEBHOOK_URL: Public URL for Telegram webhook (Railway provides this)
        DATABASE_PATH: Path to SQLite database file
        DEFAULT_TRADE_AMOUNT: Default USDT amount for new subscribers
        DEFAULT_MAX_LEVERAGE: Default max leverage for new subscribers
    """
    
    # Required
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    encryption_secret: str = Field(..., env="ENCRYPTION_SECRET", min_length=16)
    admin_telegram_id: int = Field(..., env="ADMIN_TELEGRAM_ID")
    signal_channel_id: int = Field(..., env="SIGNAL_CHANNEL_ID")
    
    # Webhook
    webhook_url: Optional[str] = Field(None, env="WEBHOOK_URL")
    webhook_path: str = Field("/webhook", env="WEBHOOK_PATH")
    
    # Server
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(8000, env="PORT")
    
    # Database
    database_path: str = Field("subscribers.db", env="DATABASE_PATH")
    
    # Trading defaults
    default_trade_amount: float = Field(50.0, env="DEFAULT_TRADE_AMOUNT")
    default_max_leverage: int = Field(10, env="DEFAULT_MAX_LEVERAGE")
    min_order_value: float = Field(8.0, env="MIN_ORDER_VALUE")
    
    # Feature flags
    allow_registration: bool = Field(True, env="ALLOW_REGISTRATION")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    @property
    def full_webhook_url(self) -> str:
        """Get the full webhook URL including path."""
        if not self.webhook_url:
            return ""
        base = self.webhook_url.rstrip("/")
        path = self.webhook_path.lstrip("/")
        return f"{base}/{path}"


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()
