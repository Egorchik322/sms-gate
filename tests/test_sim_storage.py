import tempfile
import unittest
from pathlib import Path

from app.control import TelegramControl
from app.store import GatewayStore


class SimStorageIntegrationTests(unittest.TestCase):
    def test_snapshot_is_migrated_and_rendered(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GatewayStore(Path(directory) / "gateway.sqlite3")
            store.initialize()
            store.update_modem_status(device_available=True, smsd_running=True, signal_percent=18)
            store.update_sim_storage(
                name="SM",
                used=50,
                capacity=50,
                free=0,
                percent=100,
                checked_at="2026-08-13T14:00:00+00:00",
            )
            row = store.modem_status_snapshot()
            control = TelegramControl(store, frozenset({"100"}), "200")
            rendered = control.render_action("full_status", "full_status")

        self.assertEqual(row["sim_storage_used"], 50)
        self.assertEqual(row["sim_storage_capacity"], 50)
        self.assertEqual(row["sim_storage_free"], 0)
        self.assertEqual(row["sim_storage_percent"], 100)
        self.assertIn("Память SIM (SM): 50/50", rendered)
        self.assertIn("Свободно SIM: 0", rendered)
        self.assertIn("Заполнение SIM: 100% (переполнена)", rendered)

    def test_status_without_snapshot_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GatewayStore(Path(directory) / "gateway.sqlite3")
            store.initialize()
            store.update_modem_status(device_available=True, smsd_running=True)
            rendered = TelegramControl(store, frozenset({"100"}), "200").render_action("full_status", "full_status")

        self.assertIn("Память SIM: нет данных", rendered)
        self.assertIn("Заполнение SIM: нет данных", rendered)


if __name__ == "__main__":
    unittest.main()
