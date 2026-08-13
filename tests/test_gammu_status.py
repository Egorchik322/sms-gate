import unittest

from app.gammu_status import parse_monitor_csv


class GammuMonitorTests(unittest.TestCase):
    def test_parse_gammu_142_csv_with_metadata_prefix(self):
        output = (
            "Gammu 1.42.0 on Linux, kernel;"
            ";865858057260270;250110220157012;0;0;0;0;60\n"
        )
        status = parse_monitor_csv(output)
        self.assertIsNotNone(status)
        self.assertEqual(status.sent, 0)
        self.assertEqual(status.received, 0)
        self.assertEqual(status.failed, 0)
        self.assertEqual(status.battery, 0)
        self.assertEqual(status.signal_percent, 60)
        self.assertIsNotNone(status.checked_at)

    def test_parse_monitor_csv_ignores_headers_and_malformed_output(self):
        self.assertIsNone(parse_monitor_csv("client;phone ID;IMEI;sent;received;failed;battery;signal\n"))
        self.assertIsNone(parse_monitor_csv("warning without csv"))


if __name__ == "__main__":
    unittest.main()
