import http.client
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings
from app.control import TelegramControl
from app.polling import TelegramPoller
from app.store import GatewayStore


class RemoteDisconnectedTests(unittest.TestCase):
    def test_telegram_polling_survives_proxy_disconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = GatewayStore(root / "gateway.sqlite3")
            store.initialize()
            settings = Settings(
                database_path=root / "gateway.sqlite3",
                inbox_path=root / "inbox",
                archive_path=root / "archive",
                http_proxy_url="http://proxy.example.invalid:3128",
                https_proxy_url="http://proxy.example.invalid:3128",
                telegram_bot_token="fake-token",
                telegram_chat_id="200",
                telegram_allowed_user_ids=frozenset({"100"}),
                vk_token=None,
                vk_peer_id=None,
                modem_reregistration_enabled=False,
                development_mode=True,
            )
            control = TelegramControl(store, frozenset({"100"}), "200")
            poller = TelegramPoller(settings, control)

            class DisconnectingOpener:
                def open(self, _request, timeout):
                    raise http.client.RemoteDisconnected("proxy closed connection")

            with patch("app.polling.urllib.request.build_opener", return_value=DisconnectingOpener()):
                self.assertEqual(poller.poll_once(), 0)


class RuntimeScriptContractTests(unittest.TestCase):
    def test_entrypoint_and_healthcheck_reject_dead_pid(self):
        root = Path(__file__).resolve().parents[1]
        entrypoint = (root / "scripts/entrypoint.sh").read_text()
        healthcheck = (root / "scripts/healthcheck.sh").read_text()
        self.assertIn("/proc/$pid/stat", entrypoint)
        self.assertIn('"$state" != Z', entrypoint)
        self.assertIn("/proc/$pid/stat", healthcheck)
        self.assertIn('"$state" != Z', healthcheck)


if __name__ == "__main__":
    unittest.main()
