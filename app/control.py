"""Telegram control-plane policy and reliable status rendering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .store import GatewayStore, parse_timestamp


CALLBACK_PREFIX = "smsgw:v1:"
CALLBACK_ACTIONS = {
    "status": "Состояние",
    "full_status": "Полная информация",
    "last_sms": "Последние SMS",
    "delivery": "Доставка",
    "refresh": "Обновить",
    "reregister": "Повторить регистрацию",
}


@dataclass(frozen=True)
class ControlResult:
    accepted: bool
    response: str
    action: str | None = None
    duplicate: bool = False


class TelegramControl:
    COMMANDS = {
        "Меню": "menu",
        "Состояние": "status",
        "Полная информация": "full_status",
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

    def inline_keyboard(self) -> dict[str, object]:
        rows = [
            [self._button("Состояние", "status"), self._button("Полная информация", "full_status")],
            [self._button("Последние SMS", "last_sms"), self._button("Доставка", "delivery")],
            [self._button("Обновить", "refresh")],
        ]
        if self.reregistration_enabled:
            rows.append([self._button("Повторить регистрацию", "reregister")])
        return {"inline_keyboard": rows}

    @staticmethod
    def _button(text: str, action: str) -> dict[str, str]:
        return {"text": text, "callback_data": CALLBACK_PREFIX + action}

    def _authorize_and_claim(self, *, update_id: int, user_id: str, chat_id: str) -> ControlResult | None:
        if chat_id != self.chat_id or user_id not in self.allowed_user_ids:
            return ControlResult(False, "Команда отклонена")
        if not self.store.claim_bot_update(update_id):
            return ControlResult(True, "Повторный update пропущен", duplicate=True)
        return None

    def _resolve_action(self, action: str) -> ControlResult:
        if action not in CALLBACK_ACTIONS and action != "menu":
            return ControlResult(True, "Неизвестная команда")
        if action == "reregister" and not self.reregistration_enabled:
            return ControlResult(True, "Повторная регистрация отключена", action=action)
        return ControlResult(True, action, action=action)

    def handle_update(self, *, update_id: int, user_id: str, chat_id: str, command: str) -> ControlResult:
        rejected = self._authorize_and_claim(update_id=update_id, user_id=user_id, chat_id=chat_id)
        if rejected is not None:
            return rejected
        action = self.COMMANDS.get("Меню" if command == "/start" else command)
        return self._resolve_action(action) if action else ControlResult(True, "Неизвестная команда")

    def handle_callback_update(self, *, update_id: int, user_id: str, chat_id: str, callback_data: str | None) -> ControlResult:
        rejected = self._authorize_and_claim(update_id=update_id, user_id=user_id, chat_id=chat_id)
        if rejected is not None:
            return rejected
        if not callback_data or len(callback_data.encode("utf-8")) > 64 or not callback_data.startswith(CALLBACK_PREFIX):
            return ControlResult(True, "Неизвестная команда")
        return self._resolve_action(callback_data[len(CALLBACK_PREFIX):])

    def render_action(self, action: str | None, fallback: str) -> str:
        if action == "menu":
            return "Выберите действие:"
        if action == "status":
            return self._render_compact_status()
        if action == "full_status":
            return self._render_full_status()
        if action == "last_sms":
            return self._render_last_sms()
        if action == "delivery":
            return self._render_delivery()
        if action == "refresh":
            return "Данные обновлены.\n\n" + self._render_compact_status()
        if action == "reregister":
            return "Повторная регистрация отключена" if not self.reregistration_enabled else "Повторная регистрация пока не реализована"
        return fallback

    @staticmethod
    def _freshness(timestamp: object, stale_after_seconds: int = 120) -> str:
        if not timestamp:
            return "нет данных"
        try:
            checked_at = parse_timestamp(str(timestamp))
        except (TypeError, ValueError):
            return "нет данных"
        age = max(0, int((datetime.now(UTC) - checked_at).total_seconds()))
        if age < 60:
            age_text = f"{age} с назад"
        elif age < 3600:
            age_text = f"{age // 60} мин назад"
        else:
            age_text = f"{age // 3600} ч назад"
        stale = "; устарело" if age > stale_after_seconds else ""
        return f"{checked_at.strftime('%Y-%m-%d %H:%M:%S UTC')} ({age_text}{stale})"

    @staticmethod
    def _boolean(value: object) -> str:
        return "нет данных" if value is None else ("да" if bool(value) else "нет")

    @staticmethod
    def _number(value: object) -> str:
        return str(value) if value is not None else "нет данных"

    def _reliable_lines(self, row) -> list[str]:
        signal = row["signal_percent"]
        return [
            f"Устройство: {self._boolean(row['device_available'])}",
            f"Gammu SMSD: {self._boolean(row['smsd_running'])}",
            f"Сигнал: {signal}/100" if signal is not None else "Сигнал: нет данных",
            f"Последняя SMS: {row['last_received_at'] or 'нет данных'}",
            f"SMS принято: {self._number(row['received_count'])}",
            f"SMS отправлено: {self._number(row['sent_count'])}",
        ]

    def _render_compact_status(self) -> str:
        row = self.store.modem_status_snapshot()
        if row is None:
            return "Состояние шлюза\n\nСтатус ещё не получен."
        return "\n".join([
            "Состояние шлюза",
            "",
            *self._reliable_lines(row),
            f"Обновлено: {self._freshness(row['signal_checked_at'] or row['updated_at'])}",
        ])

    def _render_full_status(self) -> str:
        row = self.store.modem_status_snapshot()
        if row is None:
            return "Полная информация\n\nСтатус ещё не получен."
        signal = row["signal_percent"]
        signal_text = f"{signal}/100" if signal is not None else "нет данных"
        dbm = row["signal_dbm"]
        ber = row["signal_bit_error_percent"]
        lines = [
            "Полная информация",
            "",
            f"Устройство: {self._boolean(row['device_available'])}",
            f"Gammu SMSD: {self._boolean(row['smsd_running'])}",
            f"Оператор: {row['operator_name'] or 'нет данных'}",
            f"Код сети: {row['network_code'] or 'нет данных'}",
            f"Регистрация: {row['registration_state'] or 'нет данных'}",
            f"Сигнал: {signal_text}",
            f"Сигнал dBm: {self._number(dbm)}",
            f"BER: {self._number(ber)}%",
            f"LAC: {row['network_lac'] or 'нет данных'}",
            f"CID: {row['network_cid'] or 'нет данных'}",
            f"GPRS: {row['gprs_state'] or 'нет данных'}",
            f"Packet: {row['packet_state'] or 'нет данных'}",
            f"Packet LAC: {row['packet_lac'] or 'нет данных'}",
            f"Packet CID: {row['packet_cid'] or 'нет данных'}",
            f"Последняя SMS: {row['last_received_at'] or 'нет данных'}",
            f"SMS принято: {self._number(row['received_count'])}",
            f"SMS отправлено: {self._number(row['sent_count'])}",
            "",
            "Источник: Gammu SMSD shared memory + C-helper",
            "Serial-порт не открывается вторым клиентом",
            "",
            "Актуальность:",
            f"Gammu: {self._freshness(row['signal_checked_at'], 120)}",
            f"Радио: {self._freshness(row['radio_checked_at'], 600)}",
            f"Память SIM: {self._freshness(row['sim_storage_checked_at'], 600)}",
            f"База: {self._freshness(row['updated_at'], 120)}",
        ]
        return "\n".join(lines)

    def _render_last_sms(self) -> str:
        rows = self.store.recent_messages(5)
        if not rows:
            return "Последние SMS\n\nНет принятых SMS."
        blocks = ["Последние SMS"]
        for row in rows:
            try:
                received = datetime.fromisoformat(row["received_at"].replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
            except (TypeError, ValueError):
                received = row["received_at"]
            blocks.append(f"\n#{row['id']} · {received}\nОт: {row['sender']}\n{row['text']}")
        return "\n".join(blocks)[:3900]

    def _render_delivery(self) -> str:
        summary = self.store.delivery_summary()
        lines = ["Доставка", ""]
        for channel in ("telegram", "vk"):
            states = summary.get(channel, {})
            details = ", ".join(f"{status}: {count}" for status, count in sorted(states.items())) or "нет записей"
            lines.append(f"{channel}: {details}")
        return "\n".join(lines)
