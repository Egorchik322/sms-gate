"""Telegram long polling through the mandatory proxy."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .config import Settings
from .control import TelegramControl
from .http_transports import JsonPoster, ProxyJsonPoster, TransportResult

LOGGER = logging.getLogger(__name__)


class TelegramPoller:
    def __init__(self, settings: Settings, control: TelegramControl, poster: JsonPoster | None = None):
        settings.require_telegram()
        self.settings = settings
        self.control = control
        self.poster = poster or ProxyJsonPoster(settings)
        self.offset = 0

    def poll_once(self, fetcher: Callable[[str, dict[str, object]], dict[str, object]] | None = None) -> int:
        params = {"timeout": 25, "allowed_updates": ["message"], "offset": self.offset}
        if fetcher is None:
            updates = self._fetch("getUpdates", params)
        else:
            updates = fetcher("getUpdates", params)
        count = 0
        for update in updates.get("result", []):
            update_id = int(update.get("update_id", 0))
            self.offset = max(self.offset, update_id + 1)
            message = update.get("message") or {}
            sender = message.get("from") or {}
            chat = message.get("chat") or {}
            command = message.get("text")
            if not command:
                continue
            result = self.control.handle_update(
                update_id=update_id,
                user_id=str(sender.get("id", "")),
                chat_id=str(chat.get("id", "")),
                command=str(command),
            )
            if result.accepted and result.response != "Повторный update пропущен":
                self._send_reply(str(chat.get("id", "")), result.response)
            count += 1
        return count

    def _fetch(self, method: str, params: dict[str, object]) -> dict[str, object]:
        query = urllib.parse.urlencode({key: json.dumps(value) if isinstance(value, list) else value for key, value in params.items()})
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/{method}?{query}"
        request = urllib.request.Request(url, method="GET")
        proxy = self.settings.require_proxy()
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler(proxy)).open(request, timeout=35) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as error:
            LOGGER.warning("telegram polling failed class=network_error")
            return {"ok": False, "result": [], "error": str(type(error).__name__)}

    def _send_reply(self, chat_id: str, text: str) -> TransportResult:
        return self.poster.post(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
            {"chat_id": chat_id, "text": text},
        )
