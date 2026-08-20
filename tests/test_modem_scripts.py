import tempfile
from pathlib import Path
import unittest

from app.main import process_is_running


ROOT = Path(__file__).resolve().parents[1]


class ModemScriptTests(unittest.TestCase):
    def test_resolver_uses_optional_path_and_stable_usb_attributes(self):
        text = (ROOT / "scripts/resolve_modem_device.sh").read_text()
        self.assertIn("usb_path=${MODEM_USB_PATH:-}", text)
        self.assertIn("ID_USB_INTERFACE_NUM", text)
        self.assertIn("ID_USB_DRIVER", text)
        self.assertIn("Multiple matching modem AT interfaces found", text)
        self.assertNotIn("MODEM_USB_PATH is required", text)
        self.assertNotIn("serial/by-id", text)

    def test_supervisor_tracks_usb_identity_not_only_tty_number(self):
        text = (ROOT / "scripts/modem-compose-supervisor.sh").read_text()
        self.assertIn("udevadm info --query=property", text)
        self.assertIn("ID_PATH", text)
        self.assertIn("ID_MODEL_ID", text)
        self.assertIn("ID_USB_INTERFACE_NUM", text)
        self.assertIn("sha256sum", text)
        self.assertIn("--force-recreate", text)
        self.assertIn('MODEM_HOST_DEVICE="$device"', text)

    def test_compose_fallback_uses_stable_alias(self):
        text = (ROOT / "compose.yml").read_text()
        self.assertIn("MODEM_HOST_DEVICE:-/dev/huawei-e3272-sms", text)

    def test_stale_gammu_pid_is_not_running(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gammu-smsd.proc"
            path.write_text("999999\n", encoding="ascii")
            self.assertFalse(process_is_running(path))


if __name__ == "__main__":
    unittest.main()
