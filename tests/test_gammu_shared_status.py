import unittest

from app.gammu_shared_status import normalize_status


class SharedGammuStatusTests(unittest.TestCase):
    def test_normalizes_network_and_signal_fields(self):
        status = normalize_status(
            {
                "Client": "gammu-smsd",
                "PhoneID": "huawei",
                "IMEI": "redacted",
                "Sent": 4,
                "Received": 7,
                "Failed": 1,
                "BatteryPercent": 80,
                "NetworkSignal": 78,
                "Network": {"Name": "beeline", "Code": "25099"},
                "NetInfo": {"LAC": "1234", "CID": "5678"},
            },
            checked_at="2026-08-19T12:00:00+00:00",
        )
        self.assertEqual(status.signal_percent, 78)
        self.assertEqual(status.network_name, "beeline")
        self.assertEqual(status.network_code, "25099")
        self.assertEqual(status.sent, 4)
        self.assertEqual(status.received, 7)
        self.assertEqual(status.failed, 1)
        self.assertEqual(status.checked_at, "2026-08-19T12:00:00+00:00")

    def test_zero_or_unknown_signal_is_not_presented_as_zero_percent(self):
        self.assertIsNone(normalize_status({"NetworkSignal": 0}).signal_percent)
        self.assertIsNone(normalize_status({"NetworkSignal": -1}).signal_percent)
        self.assertEqual(normalize_status({"NetworkSignal": 99}).signal_percent, 99)


if __name__ == "__main__":
    unittest.main()
