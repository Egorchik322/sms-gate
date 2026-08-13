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
        params = {
            "timeout": 25,
            "allowed_updates": ["message", "callback_query"],
            "offset": self.offset,
        }
        updates = self._fetch("getUpdates", params) if fetcher is None else fetcher("getUpdates", params)
        count = 0
        for update in updates.get("result", []):
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                LOGGER.warning("telegram update skipped class=invalid_update_id")
                continue
            self.offset = max(self.offset, update_id + 1)
            if "message" in update:
                self._handle_message(update_id, update.get("message") or {})
            elif "callback_query" in update:
                self._handle_callback(update_id, update.get("callback_query") or {})
            count += 1
        return count

    def _handle_message(self, update_id: int, message: dict[str, object]) -> None:
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        command = message.get("text")
        user_id = sender.get("id")
        chat_id = chat.get("id")
        if user_id is None or chat_id is None or not isinstance(command, str):
            return
        result = self.control.handle_update(
            update_id=update_id,
            user_id=str(user_id),
            chat_id=str(chat_id),
            command=command,
        )
        if not result.accepted or result.duplicate:
            return
        text = self.control.render_action(result.action, result.response)
        self._send_reply(str(chat_id), text, reply_markup=self.control.inline_keyboard())

    def _handle_callback(self, update_id: int, callback: dict[str, object]) -> None:
        callback_id = callback.get("id")
        callback_message = callback.get("message")
        message = callback_message if isinstance(callback_message, dict) else {}
        sender = callback.get("from") or {}
        chat = message.get("chat") or {}
        user_id = sender.get("id")
        chat_id = chat.get("id")
        callback_data = callback.get("data")

        if callback_id is None:
            LOGGER.warning("telegram callback skipped class=missing_callback_id")
            return

        if user_id is None or chat_id is None:
            self._answer_callback(str(callback_id), text="Команда отклонена", show_alert=True)
            return

        result = self.control.handle_callback_update(
            update_id=update_id,
            user_id=str(user_id),
            chat_id=str(chat_id),
            callback_data=callback_data if isinstance(callback_data, str) else None,
        )
        self._answer_callback(
            str(callback_id),
            text=result.response,
            show_alert=not result.accepted or result.duplicate or result.action is None,
        )
        if not result.accepted or result.duplicate or result.action is None:
            return

        text = self.control.render_action(result.action, result.response)
        markup = self.control.inline_keyboard()
        message_id = message.get("message_id")
        if not isinstance(message_id, int):
            self._send_reply(str(chat_id), text, reply_markup=markup)
            return

        edit_result = self._edit_message(str(chat_id), message_id, text, markup)
        if edit_result.outcome == "http_400":
            self._send_reply(str(chat_id), text, reply_markup=markup)
        elif edit_result.outcome != "sent":
            LOGGER.warning("telegram callback render failed class=%s", edit_result.detail or edit_result.outcome)

    def _telegram_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/{method}"

    def _fetch(self, method: str, params: dict[str, object]) -> dict[str, object]:
        query = urllib.parse.urlencode({key: json.dumps(value) if isinstance(value, list) else value for key, value in params.items()})
        request = urllib.request.Request(f"{self._telegram_url(method)}?{query}", method="GET")
        proxy = self.settings.require_proxy()
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler(proxy)).open(request, timeout=35) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as error:
            LOGGER.warning("telegram polling failed class=network_error")
            return {"ok": False, "result": [], "error": str(type(error).__name__)}

    def _send_reply(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: dict[str, object] | None = None,
    ) -> TransportResult:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self.poster.post(self._telegram_url("sendMessage"), payload)

    def _answer_callback(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> TransportResult:
        payload: dict[str, object] = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text[:200]
        return self.poster.post(self._telegram_url("answerCallbackQuery"), payload)

    def _edit_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        reply_markup: dict[str, object],
    ) -> TransportResult:
        return self.poster.post(
            self._telegram_url("editMessageText"),
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            },
        )
