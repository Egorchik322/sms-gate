import tempfile
import unittest
from pathlib import Path

from app.cpms import parse_cpms_response, parse_radio_response, read_modem_snapshot, read_sim_storage


class CpmsParserTests(unittest.TestCase):
    def test_parse_sim_and_modem_storage(self):
        status = parse_cpms_response(
            '\r\n+CPMS: "SM",50,50,"ME",0,20,"SM",50,50\r\n\r\nOK\r\n'
        )
        self.assertIsNotNone(status)
        self.assertEqual(status.name, "SM")
        self.assertEqual(status.used, 50)
        self.assertEqual(status.capacity, 50)
        self.assertEqual(status.free, 0)
        self.assertEqual(status.percent, 100)

    def test_parse_partial_or_invalid_response_returns_none(self):
        self.assertIsNone(parse_cpms_response("OK"))
        self.assertIsNone(parse_cpms_response('+CPMS: "SM",51,50'))
        self.assertIsNone(parse_cpms_response('+CPMS: "ME",1,20'))

    def test_read_sim_storage_resumes_smsd_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "gammu.pid"
            pid_path.write_text("1234\n", encoding="ascii")
            signals = []

            def fake_signal(pid, value):
                signals.append((pid, value))

            status = read_sim_storage(
                "/dev/fake-modem",
                pid_path,
                wait_seconds=0,
                signal_fn=fake_signal,
                sleep_fn=lambda _seconds: None,
                query_fn=lambda _device, _timeout: '+CPMS: "SM",50,50,"ME",0,20,"SM",50,50\\r\\nOK',
            )

        self.assertIsNotNone(status)
        self.assertEqual(signals, [(1234, 10), (1234, 12)])

    def test_read_sim_storage_resumes_smsd_after_query_error(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "gammu.pid"
            pid_path.write_text("1234\n", encoding="ascii")
            signals = []

            def fake_signal(pid, value):
                signals.append((pid, value))

            def failed_query(_device, _timeout):
                raise OSError("serial unavailable")

            status = read_sim_storage(
                "/dev/fake-modem",
                pid_path,
                wait_seconds=0,
                signal_fn=fake_signal,
                sleep_fn=lambda _seconds: None,
                query_fn=failed_query,
            )

        self.assertIsNone(status)
        self.assertEqual(signals, [(1234, 10), (1234, 12)])

    def test_combined_snapshot_uses_one_smsd_pause_for_radio_and_sim(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "gammu.pid"
            pid_path.write_text("1234\n", encoding="ascii")
            signals = []

            def fake_signal(pid, value):
                signals.append((pid, value))

            def fake_query(_device, commands, _timeout):
                self.assertEqual(commands, ("AT+CSQ", "AT+COPS?", "AT+CREG?", "AT+CEREG?", "AT+CGREG?", "AT+CPMS?"))
                return {
                    "AT+CSQ": "+CSQ: 18,255\\r\\nOK",
                    "AT+COPS?": '+COPS: 0,0,"t2 rus",2\\r\\nOK',
                    "AT+CREG?": "+CREG: 0,5\\r\\nOK",
                    "AT+CEREG?": "+CEREG: 0,2\\r\\nOK",
                    "AT+CGREG?": "+CGREG: 0,0\\r\\nOK",
                    "AT+CPMS?": '+CPMS: "SM",0,50,"ME",0,20,"SM",0,50\\r\\nOK',
                }

            snapshot = read_modem_snapshot(
                "/dev/fake-modem",
                pid_path,
                wait_seconds=0,
                signal_fn=fake_signal,
                sleep_fn=lambda _seconds: None,
                query_fn=fake_query,
            )

        self.assertIsNotNone(snapshot.radio)
        self.assertIsNotNone(snapshot.sim_storage)
        self.assertEqual(snapshot.radio.operator_name, "t2 rus")
        self.assertEqual(snapshot.radio.raw_csq, 18)
        self.assertEqual(snapshot.sim_storage.free, 50)
        self.assertEqual(signals, [(1234, 10), (1234, 12)])


if __name__ == "__main__":
    unittest.main()
