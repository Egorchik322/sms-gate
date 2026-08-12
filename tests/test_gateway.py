from __future__ import annotations

import logging.handlers
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import ConfigurationError, Settings
from app.control import TelegramControl
from app.delivery import DeliveryResult, DeliveryWorker, RecordingTransport
from app.http_transports import VK_API_ENDPOINT, VkTransport, classify_http
from app.ingress import FilesIngress, decode_gammu_text
from app.polling import TelegramPoller
from app.store import GatewayStore


class FakePoster:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def post(self, url, payload):
        self.calls.append((url, payload))
        return self.result


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "gateway.sqlite3"
        self.inbox = root / "inbox"
        self.archive = root / "processed"
        self.store = GatewayStore(self.db)
        self.store.initialize()
        self.ingress = FilesIngress(self.store, self.inbox, self.archive)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_sms(self, filename: str, text: str, encoding: str = "utf-8") -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        (self.inbox / filename).write_text(text, encoding=encoding)

    def count(self, table: str) -> int:
        with self.store.connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def test_ingestion_and_unicode_fixtures(self) -> None:
        self.write_sms("IN20260810_000900_00_+15550001001_00.txt", "Test message")
        self.write_sms("IN20260810_000901_00_+15550001002_00.txt", "Привет, мир")
        self.write_sms("IN20260810_000902_00_+15550001003_00.txt", "你好，世界")
        ids = self.ingress.ingest_pending()
        self.assertEqual(len(ids), 3)
        with self.store.connect() as connection:
            rows = connection.execute("SELECT sender, text FROM messages ORDER BY id").fetchall()
        self.assertEqual([row["text"] for row in rows], ["Test message", "Привет, мир", "你好，世界"])
        self.assertEqual(self.count("deliveries"), 6)

    def test_utf16_gammu_text_is_decoded(self) -> None:
        path = Path(self.temp.name) / "unicode.txt"
        path.write_text("Привет, модем", encoding="utf-16")
        self.assertEqual(decode_gammu_text(path), "Привет, модем")

    def test_multipart_parts_are_combined_in_sequence_order(self) -> None:
        self.write_sms("IN20260810_001000_42_+15550001004_01.txt", "часть 2", encoding="utf-16")
        self.write_sms("IN20260810_001000_42_+15550001004_00.txt", "часть 1 ", encoding="utf-16")
        ids = self.ingress.ingest_pending()
        self.assertEqual(len(ids), 1)
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM messages").fetchone()
        self.assertEqual(row["text"], "часть 1 часть 2")
        self.assertEqual(row["multipart_total"], 2)
        self.assertEqual(row["multipart_reference"], "IN20260810_001000_42_+15550001004")

    def test_same_sender_and_text_are_not_deduplicated(self) -> None:
        self.write_sms("IN20260810_001100_01_+15550001005_00.txt", "same")
        self.write_sms("IN20260810_001101_02_+15550001005_00.txt", "same")
        self.assertEqual(len(self.ingress.ingest_pending()), 2)
        self.assertEqual(self.count("messages"), 2)
        self.assertEqual(self.count("deliveries"), 4)

    def test_store_ingestion_is_idempotent(self) -> None:
        first = self.store.ingest_message(source_identifier="source-1", sender="+15550001006", received_at="2026-08-10T00:00:00+00:00", text="one")
        second = self.store.ingest_message(source_identifier="source-1", sender="+15550001006", received_at="2026-08-10T00:00:00+00:00", text="one")
        self.assertEqual(first, (1, True))
        self.assertEqual(second, (1, False))
        self.assertEqual(self.count("messages"), 1)
        self.assertEqual(self.count("deliveries"), 2)

    def test_channels_are_independent(self) -> None:
        self.store.ingest_message(source_identifier="source-2", sender="+15550001007", received_at="2026-08-10T00:00:00+00:00", text="payload")
        telegram = RecordingTransport("telegram")
        vk = RecordingTransport("vk", DeliveryResult("transient", retry_after_seconds=42, detail="http_429"))
        self.assertEqual(DeliveryWorker(self.store, telegram).run_once(), 1)
        self.assertEqual(DeliveryWorker(self.store, vk).run_once(), 0)
        with self.store.connect() as connection:
            rows = connection.execute("SELECT channel, status, attempts, last_error, next_attempt_at FROM deliveries ORDER BY channel").fetchall()
        self.assertEqual([(row["channel"], row["status"]) for row in rows], [("telegram", "sent"), ("vk", "retry")])
        self.assertEqual(rows[1]["attempts"], 1)
        self.assertEqual(rows[1]["last_error"], "http_429")
        self.assertIsNotNone(rows[1]["next_attempt_at"])

    def test_retry_survives_new_store_instance(self) -> None:
        self.store.ingest_message(source_identifier="source-3", sender="+15550001008", received_at="2026-08-10T00:00:00+00:00", text="retry")
        DeliveryWorker(self.store, RecordingTransport("telegram", DeliveryResult("transient", detail="network_error"))).run_once()
        restarted = GatewayStore(self.db)
        with restarted.connect() as connection:
            row = connection.execute("SELECT status, attempts, next_attempt_at FROM deliveries WHERE channel='telegram'").fetchone()
        self.assertEqual(row["status"], "retry")
        self.assertEqual(row["attempts"], 1)
        self.assertIsNotNone(row["next_attempt_at"])

    def test_telegram_update_whitelist_and_idempotency(self) -> None:
        control = TelegramControl(self.store, frozenset({"100"}), "200")
        self.assertFalse(control.handle_update(update_id=1, user_id="999", chat_id="200", command="Состояние").accepted)
        self.assertEqual(control.handle_update(update_id=1, user_id="100", chat_id="200", command="Состояние").response, "status")
        self.assertEqual(control.handle_update(update_id=1, user_id="100", chat_id="200", command="Состояние").response, "Повторный update пропущен")
        self.assertEqual(control.handle_update(update_id=2, user_id="100", chat_id="200", command="Повторить регистрацию").response, "Повторная регистрация отключена")

    def test_outage_and_recovery_create_one_pair_each(self) -> None:
        unavailable_since = datetime.now(UTC) - timedelta(minutes=6)
        self.assertEqual(self.store.update_outage(unavailable_since), "outage")
        self.assertIsNone(self.store.update_outage(unavailable_since))
        self.assertEqual(self.store.update_outage(None), "recovery")
        self.assertIsNone(self.store.update_outage(None))
        with self.store.connect() as connection:
            events = [row[0] for row in connection.execute("SELECT event_type FROM audit_events ORDER BY id")]
            messages = connection.execute("SELECT sender, text FROM messages ORDER BY id").fetchall()
            deliveries = connection.execute("SELECT channel, status FROM deliveries ORDER BY id").fetchall()
        self.assertEqual(events, ["outage_opened", "outage_recovered"])
        self.assertEqual(len(messages), 2)
        self.assertEqual(len(deliveries), 4)
        self.assertEqual([row["channel"] for row in deliveries], ["telegram", "vk", "telegram", "vk"])

    def test_missing_proxy_is_configuration_error(self) -> None:
        settings = Settings(database_path=self.db, inbox_path=self.inbox, archive_path=self.archive, http_proxy_url=None, https_proxy_url=None, telegram_bot_token=None, telegram_chat_id=None, telegram_allowed_user_ids=frozenset(), vk_token=None, vk_peer_id=None, modem_reregistration_enabled=False, development_mode=False)
        with self.assertRaises(ConfigurationError):
            settings.require_proxy()

    def test_http_status_classification(self) -> None:
        self.assertEqual(classify_http(200, None).outcome, "sent")
        self.assertEqual(classify_http(429, "17").retry_after_seconds, 17)
        self.assertEqual(classify_http(401, None).outcome, "configuration")
        self.assertEqual(classify_http(400, None).outcome, "http_400")
        self.assertEqual(classify_http(503, None).outcome, "transient")

    def test_vk_uses_fixed_direct_endpoint_without_proxy(self) -> None:
        settings = Settings(database_path=self.db, inbox_path=self.inbox, archive_path=self.archive, http_proxy_url=None, https_proxy_url=None, telegram_bot_token=None, telegram_chat_id=None, telegram_allowed_user_ids=frozenset(), vk_token="fake-vk-token", vk_peer_id="fake-peer", modem_reregistration_enabled=False, development_mode=True)
        poster = FakePoster(DeliveryResult("sent"))
        transport = VkTransport(settings, poster=poster)
        self.assertEqual(transport.send(7, "+15550001010", "2026-08-10T00:00:00+00:00", "fictional body").outcome, "sent")
        self.assertEqual(poster.calls[0][0], VK_API_ENDPOINT)
        self.assertNotIn("proxy", poster.calls[0][0].lower())

    def test_telegram_polling_uses_saved_update_id_and_fake_reply(self) -> None:
        settings = Settings(database_path=self.db, inbox_path=self.inbox, archive_path=self.archive, http_proxy_url="http://proxy.example.invalid:3128", https_proxy_url="http://proxy.example.invalid:3128", telegram_bot_token="fake-token", telegram_chat_id="200", telegram_allowed_user_ids=frozenset({"100"}), vk_token=None, vk_peer_id=None, modem_reregistration_enabled=False, development_mode=True)
        control = TelegramControl(self.store, settings.telegram_allowed_user_ids, settings.telegram_chat_id)
        poster = FakePoster(DeliveryResult("sent"))
        poller = TelegramPoller(settings, control, poster=poster)
        update = {"result": [{"update_id": 9, "message": {"from": {"id": 100}, "chat": {"id": 200}, "text": "Состояние"}}]}
        self.assertEqual(poller.poll_once(lambda _method, _params: update), 1)
        self.assertEqual(poller.poll_once(lambda _method, _params: update), 1)
        self.assertEqual(len(poster.calls), 1)
        self.assertEqual(poller.offset, 10)

    def test_logs_do_not_contain_sms_body_or_secrets(self) -> None:
        body = "OTP-FAKE-123456 secret-message"
        self.store.ingest_message(source_identifier="source-4", sender="+15550001009", received_at="2026-08-10T00:00:00+00:00", text=body)
        logger = logging.getLogger("app.delivery")
        handler = logging.handlers.BufferingHandler(20)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            DeliveryWorker(self.store, RecordingTransport("telegram", DeliveryResult("transient", detail="network_error"))).run_once()
            rendered = "\n".join(record.getMessage() for record in handler.buffer)
        finally:
            logger.removeHandler(handler)
        self.assertNotIn(body, rendered)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("token", rendered.lower())


if __name__ == "__main__":
    unittest.main()
