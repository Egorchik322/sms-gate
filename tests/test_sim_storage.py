import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.control import TelegramControl
from app.store import GatewayStore


class SimStorageIntegrationTests(unittest.TestCase):
    def test_snapshot_is_stored_but_not_rendered_in_telegram(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GatewayStore(Path(directory) / "gateway.sqlite3")
            store.initialize()
            now = datetime.now(UTC).replace(microsecond=0).isoformat()
            store.update_modem_status(device_available=True, smsd_running=True, signal_percent=18, signal_checked_at=now)
            store.update_sim_storage(name="SM", used=50, capacity=50, free=0, percent=100, checked_at=now)
            row = store.modem_status_snapshot()
            rendered = TelegramControl(store, frozenset({"100"}), "200").render_action("full_status", "full_status")

        self.assertEqual(row["sim_storage_used"], 50)
        self.assertEqual(row["sim_storage_capacity"], 50)
        self.assertEqual(row["sim_storage_free"], 0)
        self.assertEqual(row["sim_storage_percent"], 100)
        self.assertIn("Источник статуса: Gammu SMSD shared memory", rendered)
        self.assertNotIn("Память SIM (SM):", rendered)
        self.assertNotIn("Заполнение SIM: 100%", rendered)

    def test_status_without_snapshot_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GatewayStore(Path(directory) / "gateway.sqlite3")
            store.initialize()
            store.update_modem_status(device_available=True, smsd_running=True)
            rendered = TelegramControl(store, frozenset({"100"}), "200").render_action("full_status", "full_status")

        self.assertIn("Источник статуса: Gammu SMSD shared memory", rendered)
        self.assertNotIn("Память SIM", rendered)


if __name__ == "__main__":
    unittest.main()
