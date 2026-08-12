"""Telegram control-plane policy without transport code."""
from __future__ import annotations

from dataclasses import dataclass

from .store import GatewayStore


@dataclass(frozen=True)
class ControlResult:
    accepted: bool
    response: str


class TelegramControl:
    COMMANDS = {
        "Состояние": "status",
        "Последние SMS": "last_sms",
        "Доставка": "delivery",
        "Обновить": "refresh",
        "Повторить регистрацию": "reregister",
    }

    def __init__(self, store: GatewayStore, allowed_user_ids: frozenset[str], chat_id: str | None, reregistration_enabled: bool = False):
        self.store = store
        self.allowed_user_ids = allowed_user_ids
        self.chat_id = chat_id
        self.reregistration_enabled = reregistration_enabled

    def handle_update(self, *, update_id: int, user_id: str, chat_id: str, command: str) -> ControlResult:
        if chat_id != self.chat_id or user_id not in self.allowed_user_ids:
            return ControlResult(False, "Команда отклонена")
        if not self.store.claim_bot_update(update_id):
            return ControlResult(True, "Повторный update пропущен")
        action = self.COMMANDS.get(command)
        if action is None:
            return ControlResult(True, "Неизвестная команда")
        if action == "reregister" and not self.reregistration_enabled:
            return ControlResult(True, "Повторная регистрация отключена")
        return ControlResult(True, action)
