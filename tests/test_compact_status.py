import tempfile
import unittest
from pathlib import Path

from app.control import CALLBACK_PREFIX, TelegramControl
from app.store import GatewayStore


class CompactStatusTests(unittest.TestCase):
    def make_control(self):
        self.temp = tempfile.TemporaryDirectory()
        store = GatewayStore(Path(self.temp.name) / "gateway.sqlite3")
        store.initialize()
        store.update_modem_status(
            device_available=True,
            smsd_running=True,
            operator_name="t2 rus",
            signal_percent=48,
            signal_checked_at="2026-08-13T16:00:00+00:00",
            last_contact_at="2026-08-13T16:00:00+00:00",
        )
        return store, TelegramControl(store, frozenset({"100"}), "200")

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def test_compact_status_hides_extended_diagnostics(self):
        _store, control = self.make_control()
        rendered = control.render_action("status", "status")
        self.assertIn("Оператор: t2 rus", rendered)
        self.assertIn("Сигнал: 48/100", rendered)
        self.assertNotIn("Сырой CSQ", rendered)
        self.assertNotIn("Регистрация:", rendered)
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

    def test_full_status_contains_extended_diagnostics(self):
        store, control = self.make_control()
        store.update_radio_status(
            operator_name="t2 rus",
            network_code=None,
            access_technology="UTRAN/3G",
            registration_state="роуминг (5)",
            packet_registration_state="поиск сети (2)",
            gprs_registration_state="не зарегистрирован (0)",
            raw_csq=18,
            checked_at="2026-08-13T16:00:00+00:00",
        )
        rendered = control.render_action("full_status", "full_status")
        self.assertIn("Сырой CSQ: 18/31", rendered)
        self.assertIn("Регистрация: роуминг (5)", rendered)
        self.assertIn("Актуальность:", rendered)


if __name__ == "__main__":
    unittest.main()
