"""
Configuration loader using Pydantic Settings.
Loads environment variables from .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Telegram (optional - service can run API-only without these)
    telegram_api_id: int = Field(default=0, description="Telegram API ID")
    telegram_api_hash: str = Field(default="", description="Telegram API Hash")
    telegram_phone: str = Field(default="", description="Phone number for Telegram auth")
    
    @property
    def telegram_configured(self) -> bool:
        """Check if Telegram credentials are properly configured."""
        return (
            self.telegram_api_id > 0 and 
            self.telegram_api_hash and 
            self.telegram_api_hash not in ("", "your_api_hash_here", "not_configured") and
            self.telegram_phone and
            self.telegram_phone not in ("", "+959xxxxxxxxx", "not_configured")
        )
    
    # Groq LLM
    groq_api_key: str = Field(..., description="Groq API Key")
    
    # Database (SQLite for local dev, PostgreSQL for production)
    database_url: str = Field(
        default="sqlite+aiosqlite:///./telegram_listener.db",
        description="Database connection string"
    )
    
    # Channels (comma-separated in env, parsed to list)
    channels: str = Field(default="", description="Comma-separated channel usernames")
    
    # API (Render uses PORT env var, default to 10000)
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=10000, alias="PORT", description="API port")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    
    @property
    def channel_list(self) -> List[str]:
        """Parse comma-separated channels into a list."""
        if not self.channels:
            return []
        return [ch.strip() for ch in self.channels.split(",") if ch.strip()]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
