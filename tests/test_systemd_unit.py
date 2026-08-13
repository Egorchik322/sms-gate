from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "deploy/systemd/sms-gateway-modem-supervisor.service"


class SystemdUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = UNIT.read_text(encoding="utf-8")

    def test_unit_starts_after_docker_and_restarts(self):
        self.assertIn("After=network-online.target docker.service", self.text)
        self.assertIn("Requires=docker.service", self.text)
        self.assertIn("Restart=always", self.text)
        self.assertIn("RestartSec=10", self.text)

    def test_unit_runs_host_supervisor_with_hardware_metadata(self):
        self.assertIn("ExecStart=/workspace/sms-gateway/scripts/modem-compose-supervisor.sh", self.text)
        self.assertIn("MODEM_USB_PATH=", self.text)
        self.assertIn("MODEM_VENDOR_ID=12d1", self.text)
        self.assertIn("MODEM_PRODUCT_IDS=1506", self.text)
        self.assertIn("MODEM_INTERFACE_NUM=00", self.text)

    def test_unit_does_not_mount_docker_socket_or_use_privileged_mode(self):
        self.assertNotIn("docker.sock", self.text)
        self.assertNotIn("privileged", self.text.lower())


if __name__ == "__main__":
    unittest.main()
