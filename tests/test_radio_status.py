import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.control import TelegramControl
from app.cpms import parse_radio_response, read_radio_status
from app.store import GatewayStore


class RadioParserTests(unittest.TestCase):
    def test_parse_radio_snapshot_for_roaming_modem(self):
        output = """
AT+CSQ
+CSQ: 18,255
OK
AT+COPS?
+COPS: 0,0,"t2 rus",2
OK
AT+CREG?
+CREG: 0,5
OK
AT+CEREG?
+CEREG: 0,2
OK
AT+CGREG?
+CGREG: 0,0
OK
"""
        status = parse_radio_response(output)
        self.assertIsNotNone(status)
        self.assertEqual(status.raw_csq, 18)
        self.assertEqual(status.operator_name, "t2 rus")
        self.assertIsNone(status.network_code)
        self.assertEqual(status.access_technology, "UTRAN/3G")
        self.assertEqual(status.registration_state, "роуминг (5)")
        self.assertEqual(status.packet_registration_state, "поиск сети (2)")
        self.assertEqual(status.gprs_registration_state, "не зарегистрирован (0)")

    def test_parse_radio_rejects_unknown_signal_only(self):
        status = parse_radio_response('+CSQ: 99,255\nOK')
        self.assertIsNotNone(status)
        self.assertIsNone(status.raw_csq)

    def test_read_radio_status_resumes_smsd_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "gammu.pid"
            pid_path.write_text("1234\n", encoding="ascii")
            signals = []

            def fake_signal(pid, value):
                signals.append((pid, value))

            status = read_radio_status(
                "/dev/fake-modem",
                pid_path,
                wait_seconds=0,
                signal_fn=fake_signal,
                sleep_fn=lambda _seconds: None,
                query_fn=lambda _device, _timeout: (_ for _ in ()).throw(OSError("serial unavailable")),
            )

        self.assertIsNone(status)
        self.assertEqual(signals, [(1234, 10), (1234, 12)])


class RadioStorageIntegrationTests(unittest.TestCase):
    def test_full_status_hides_unreliable_at_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GatewayStore(Path(directory) / "gateway.sqlite3")
            store.initialize()
            now = datetime.now(UTC).replace(microsecond=0).isoformat()
            store.update_modem_status(device_available=True, smsd_running=True, signal_percent=48, signal_checked_at=now)
            store.update_radio_status(
                operator_name="t2 rus",
                network_code=None,
                access_technology="UTRAN/3G",
                registration_state="роуминг (5)",
                packet_registration_state="поиск сети (2)",
                gprs_registration_state="не зарегистрирован (0)",
                raw_csq=18,
                checked_at=now,
            )
            store.update_sim_storage(name="SM", used=0, capacity=50, free=50, percent=0, checked_at=now)
            rendered = TelegramControl(store, frozenset({"100"}), "200").render_action("full_status", "full_status")

        self.assertIn("Сигнал: 48/100", rendered)
        self.assertIn("Источник статуса: Gammu SMSD shared memory", rendered)
        self.assertNotIn("t2 rus", rendered)
        self.assertNotIn("UTRAN/3G", rendered)
        self.assertNotIn("Сырой CSQ:", rendered)
        self.assertNotIn("Память SIM", rendered)

    def test_old_snapshot_is_not_rendered_as_live_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GatewayStore(Path(directory) / "gateway.sqlite3")
            store.initialize()
            old = (datetime.now(UTC) - timedelta(hours=2)).replace(microsecond=0).isoformat()
            store.update_modem_status(device_available=True, smsd_running=True, signal_percent=48, signal_checked_at=old)
            rendered = TelegramControl(store, frozenset({"100"}), "200").render_action("full_status", "full_status")

        self.assertIn("Сигнал: 48/100", rendered)
        self.assertIn("Источник статуса: Gammu SMSD shared memory", rendered)
        self.assertNotIn("Оператор:", rendered)


if __name__ == "__main__":
    unittest.main()
