"""Production HTTP transports for Telegram and VK.

Telegram traffic is forced through the configured proxies. VK traffic uses a
fixed official host and an explicitly proxy-free opener. Neither transport
accepts a user-provided endpoint, and diagnostics never log payloads.
"""
from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .config import Settings

LOGGER = logging.getLogger(__name__)
VK_API_ENDPOINT = "https://api.vk.com/method/messages.send"


@dataclass(frozen=True)
class TransportResult:
    outcome: str
    retry_after_seconds: int | None = None
    detail: str | None = None


class JsonPoster(Protocol):
    def post(self, url: str, payload: dict[str, object]) -> TransportResult:
        ...


class _UrllibPoster:
    def __init__(self, opener: urllib.request.OpenerDirector, *, form_encoded: bool):
        self._opener = opener
        self._form_encoded = form_encoded

    def post(self, url: str, payload: dict[str, object]) -> TransportResult:
        if self._form_encoded:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=15) as response:
                body = response.read(256 * 1024)
                return classify_response(response.status, response.headers.get("Retry-After"), body)
        except urllib.error.HTTPError as error:
            body = error.read(256 * 1024)
            return classify_response(error.code, error.headers.get("Retry-After"), body)
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            return TransportResult("transient", detail="network_error")


class ProxyJsonPoster(_UrllibPoster):
    def __init__(self, settings: Settings):
        super().__init__(urllib.request.build_opener(urllib.request.ProxyHandler(settings.require_proxy())), form_encoded=False)


class DirectJsonPoster(_UrllibPoster):
    """Direct VK poster; VK parameters are sent as form data, never JSON."""

    def __init__(self):
        super().__init__(urllib.request.build_opener(urllib.request.ProxyHandler({})), form_encoded=True)


def classify_response(status: int, retry_after: str | None, body: bytes) -> TransportResult:
    """Classify HTTP and API-level errors without exposing response body."""
    http_result = classify_http(status, retry_after)
    if http_result.outcome != "sent":
        return http_result
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return TransportResult("transient", detail="invalid_api_response")
    if payload.get("ok") is False:
        return TransportResult("http_400", detail="telegram_api_error")
    if isinstance(payload.get("error"), dict):
        code = payload["error"].get("error_code")
        if code in {5, 7, 15}:
            return TransportResult("configuration", detail="vk_api_configuration")
        if code in {6, 9, 10, 14}:
            return TransportResult("transient", detail="vk_api_transient")
        return TransportResult("http_400", detail="vk_api_error")
    return TransportResult("sent")


def classify_http(status: int, retry_after: str | None) -> TransportResult:
    if 200 <= status < 300:
        return TransportResult("sent")
    if status == 429:
        try:
            delay = max(1, int(retry_after or "60"))
        except ValueError:
            delay = 60
        return TransportResult("transient", retry_after_seconds=delay, detail="http_429")
    if status in (401, 403):
        return TransportResult("configuration", detail=f"http_{status}")
    if status == 400:
        return TransportResult("http_400", detail="http_400")
    if 500 <= status <= 599:
        return TransportResult("transient", detail=f"http_{status}")
    return TransportResult("transient", detail=f"http_{status}")


def notification(message_id: int, sender: str, received_at: str, text: str) -> str:
    timestamp = datetime.fromisoformat(received_at.replace("Z", "+00:00")).astimezone(UTC)
    return f"Новое SMS · #{message_id}\n\nОт: {sender}\nВремя: {timestamp:%d.%m.%Y %H:%M}\n\n{text}"


class TelegramTransport:
    channel = "telegram"

    def __init__(self, settings: Settings, poster: JsonPoster | None = None):
        settings.require_telegram()
        self.settings = settings
        self.poster = poster or ProxyJsonPoster(settings)

    def send(self, message_id: int, sender: str, received_at: str, text: str) -> TransportResult:
        endpoint = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        return self.poster.post(endpoint, {"chat_id": self.settings.telegram_chat_id, "text": notification(message_id, sender, received_at, text)})


class VkTransport:
    channel = "vk"

    def __init__(self, settings: Settings, poster: JsonPoster | None = None):
        settings.require_vk()
        self.settings = settings
        self.poster = poster or DirectJsonPoster()

    def send(self, message_id: int, sender: str, received_at: str, text: str) -> TransportResult:
        return self.poster.post(
            VK_API_ENDPOINT,
            {
                "peer_id": self.settings.vk_peer_id,
                "random_id": message_id,
                "message": notification(message_id, sender, received_at, text),
                "access_token": self.settings.vk_token,
                "v": "5.199",
            },
        )
