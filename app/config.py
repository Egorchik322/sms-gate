"""Configuration loaded exclusively from environment variables."""
from __future__ import annotations

from dataclasses import dataclass
from os import environ
from pathlib import Path


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    database_path: Path
    inbox_path: Path
    archive_path: Path
    http_proxy_url: str | None
    https_proxy_url: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    telegram_allowed_user_ids: frozenset[str]
    vk_token: str | None
    vk_peer_id: str | None
    modem_reregistration_enabled: bool
    development_mode: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        allowed_users = frozenset(value.strip() for value in environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if value.strip())
        return cls(
            database_path=Path(environ.get("DATABASE_PATH", "/data/gateway.sqlite3")),
            inbox_path=Path(environ.get("GAMMU_INBOX_PATH", "/data/gammu/inbox")),
            archive_path=Path(environ.get("GAMMU_ARCHIVE_PATH", "/data/gammu/processed")),
            http_proxy_url=environ.get("HTTP_PROXY_URL"),
            https_proxy_url=environ.get("HTTPS_PROXY_URL"),
            telegram_bot_token=environ.get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=environ.get("TELEGRAM_CHAT_ID"),
            telegram_allowed_user_ids=allowed_users,
            vk_token=environ.get("VK_TOKEN"),
            vk_peer_id=environ.get("VK_PEER_ID"),
            modem_reregistration_enabled=environ.get("MODEM_REREGISTRATION_ENABLED", "false").lower() == "true",
            development_mode=environ.get("GATEWAY_DEVELOPMENT_MODE", "false").lower() == "true",
        )

    def require_proxy(self) -> dict[str, str]:
        if not self.http_proxy_url or not self.https_proxy_url:
            raise ConfigurationError("HTTP_PROXY_URL and HTTPS_PROXY_URL are required; direct connections are disabled")
        return {"http": self.http_proxy_url, "https": self.https_proxy_url}

    def require_telegram(self) -> None:
        if not self.telegram_bot_token or not self.telegram_chat_id or not self.telegram_allowed_user_ids:
            raise ConfigurationError("Telegram token, chat ID, and allowed user IDs are required")

    def require_vk(self) -> None:
        if not self.vk_token or not self.vk_peer_id:
            raise ConfigurationError("VK token and peer ID are required")
