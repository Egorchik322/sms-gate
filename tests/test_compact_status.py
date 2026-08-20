import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.control import CALLBACK_PREFIX, TelegramControl
from app.store import GatewayStore


class CompactStatusTests(unittest.TestCase):
    def make_control(self):
        self.temp = tempfile.TemporaryDirectory()
        store = GatewayStore(Path(self.temp.name) / "gateway.sqlite3")
        store.initialize()
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        store.update_modem_status(
            device_available=True,
            smsd_running=True,
            signal_percent=48,
            signal_checked_at=now,
            last_contact_at=now,
            received_count=3,
            sent_count=2,
        )
        return store, TelegramControl(store, frozenset({"100"}), "200")

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def test_compact_status_contains_only_live_monitor_fields(self):
        _store, control = self.make_control()
        rendered = control.render_action("status", "status")
        self.assertIn("Устройство: да", rendered)
        self.assertIn("Gammu SMSD: да", rendered)
        self.assertIn("Сигнал: 48/100", rendered)
        self.assertIn("SMS принято: 3", rendered)
        self.assertNotIn("Оператор:", rendered)
        self.assertNotIn("Сырой CSQ", rendered)
        self.assertNotIn("Память SIM", rendered)
        self.assertNotIn("Актуальность:", rendered)

    def test_full_status_button_and_callback(self):
        _store, control = self.make_control()
        callbacks = [button["callback_data"] for row in control.inline_keyboard()["inline_keyboard"] for button in row]
        self.assertIn(CALLBACK_PREFIX + "full_status", callbacks)
        result = control.handle_callback_update(
            update_id=100,
            user_id="100",
            chat_id="200",
            callback_data=CALLBACK_PREFIX + "full_status",
        )
        self.assertEqual(result.action, "full_status")

    def test_full_status_contains_shared_memory_source(self):
        _store, control = self.make_control()
        rendered = control.render_action("full_status", "full_status")
        self.assertIn("Сигнал: 48/100", rendered)
        self.assertIn("Источник: Gammu SMSD shared memory + C-helper", rendered)
        self.assertIn("Оператор: нет данных", rendered)
        self.assertIn("Регистрация: нет данных", rendered)
        self.assertIn("Память SIM: нет данных", rendered)
        self.assertNotIn("Сырой CSQ", rendered)


if __name__ == "__main__":
    unittest.main()
