import unittest

from app.gammu_c_status import parse_helper_output


class CHelperStatusTests(unittest.TestCase):
    def test_parse_rich_shared_memory_status(self):
        status = parse_helper_output(
            '{"version":2,"signal_percent":75,"signal_dbm":-63,"bit_error_percent":-1,'
            '"sent":0,"received":0,"failed":0,"network_name":"beeline",'
            '"network_code":"250 99","network_state":"roaming","lac":"8F90",'
            '"cid":"04AF3D13","gprs_state":"attached","packet_state":"roaming",'
            '"packet_lac":"8F90","packet_cid":"04AF3D13"}',
            checked_at="2026-08-19T12:00:00+00:00",
        )
        self.assertIsNotNone(status)
        self.assertEqual(status.network_name, "beeline")
        self.assertEqual(status.network_code, "250 99")
        self.assertEqual(status.signal_percent, 75)
        self.assertEqual(status.signal_dbm, -63)
        self.assertEqual(status.network_state, "roaming")
        self.assertEqual(status.gprs_state, "attached")
        self.assertEqual(status.lac, "8F90")
        self.assertEqual(status.cid, "04AF3D13")

    def test_invalid_helper_output_is_ignored(self):
        self.assertIsNone(parse_helper_output("not json"))


if __name__ == "__main__":
    unittest.main()
