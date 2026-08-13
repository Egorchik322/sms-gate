from pathlib import Path
import tempfile
import unittest

from app.main import process_is_running


ROOT = Path(__file__).resolve().parents[1]


class ModemScriptTests(unittest.TestCase):
    def test_resolver_requires_physical_usb_path_and_checks_interface(self):
        text = (ROOT / "scripts/resolve_modem_device.sh").read_text()
        self.assertIn("MODEM_USB_PATH is required", text)
        self.assertIn("ID_USB_INTERFACE_NUM", text)
        self.assertIn("ID_USB_DRIVER", text)
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

    def test_stale_gammu_pid_is_not_running(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gammu-smsd.proc"
            path.write_text("999999\n", encoding="ascii")
            self.assertFalse(process_is_running(path))


if __name__ == "__main__":
    unittest.main()
