"""SQLite persistence for the SMS gateway."""
from __future__ import annotations

import hashlib
import random
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "migrations" / "001_initial.sql"


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GatewayStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            columns = {row[1] for row in connection.execute("PRAGMA table_info(modem_status)")}
            additions = {
                "sent_count": "INTEGER",
                "received_count": "INTEGER",
                "failed_count": "INTEGER",
                "radio_access_technology": "TEXT",
                "registration_state": "TEXT",
                "packet_registration_state": "TEXT",
                "gprs_registration_state": "TEXT",
                "raw_csq": "INTEGER",
                "radio_checked_at": "TEXT",
                "signal_checked_at": "TEXT",
                "sim_storage_name": "TEXT",
                "sim_storage_used": "INTEGER",
                "sim_storage_capacity": "INTEGER",
                "sim_storage_free": "INTEGER",
                "sim_storage_percent": "INTEGER",
                "sim_storage_checked_at": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE modem_status ADD COLUMN {name} {definition}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _fingerprint(source_identifier: str, sender: str, received_at: str, text: str, multipart_reference: str | None, multipart_total: int | None, multipart_sequence: int | None) -> str:
        value = "\x1f".join((source_identifier, sender, received_at, text, multipart_reference or "", str(multipart_total or ""), str(multipart_sequence or "")))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _create_delivery_rows(connection: sqlite3.Connection, message_id: int, now: str) -> None:
        for channel in ("telegram", "vk"):
            connection.execute(
                """
                INSERT INTO deliveries (
                    message_id, channel, status, attempts, next_attempt_at,
                    created_at, updated_at
                ) VALUES (?, ?, 'pending', 0, ?, ?, ?)
                """,
                (message_id, channel, now, now, now),
            )

    def ingest_message(
        self,
        *,
        source_identifier: str,
        sender: str,
        received_at: str,
        text: str,
        multipart_reference: str | None = None,
        multipart_total: int | None = None,
        multipart_sequence: int | None = None,
    ) -> tuple[int, bool]:
        fingerprint = self._fingerprint(source_identifier, sender, received_at, text, multipart_reference, multipart_total, multipart_sequence)
        now = utcnow()
        with self.transaction() as connection:
            existing = connection.execute("SELECT id FROM messages WHERE source_identifier = ?", (source_identifier,)).fetchone()
            if existing:
                return int(existing["id"]), False
            cursor = connection.execute(
                """
                INSERT INTO messages (
                    source_identifier, sender, received_at, text, multipart_reference,
                    multipart_total, multipart_sequence, fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source_identifier, sender, received_at, text, multipart_reference, multipart_total, multipart_sequence, fingerprint, now),
            )
            message_id = int(cursor.lastrowid)
            self._create_delivery_rows(connection, message_id, now)
            connection.execute("INSERT INTO audit_events (event_type, message_id, created_at) VALUES (?, ?, ?)", ("sms_ingested", message_id, now))
            return message_id, True

    def _create_system_event(self, connection: sqlite3.Connection, event_type: str, text: str, now: str) -> None:
        source_identifier = f"system:{event_type}:{now}"
        cursor = connection.execute(
            """
            INSERT INTO messages (
                source_identifier, sender, received_at, text, fingerprint, created_at
            ) VALUES (?, 'system', ?, ?, ?, ?)
            """,
            (source_identifier, now, text, self._fingerprint(source_identifier, "system", now, text, None, None, None), now),
        )
        message_id = int(cursor.lastrowid)
        self._create_delivery_rows(connection, message_id, now)
        connection.execute("INSERT INTO audit_events (event_type, message_id, created_at) VALUES (?, ?, ?)", (event_type, message_id, now))

    def due_deliveries(self, channel: str, now: str | None = None) -> list[sqlite3.Row]:
        now = now or utcnow()
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT deliveries.*, messages.sender, messages.received_at, messages.text
                FROM deliveries JOIN messages ON messages.id = deliveries.message_id
                WHERE deliveries.channel = ?
                  AND deliveries.status IN ('pending', 'retry')
                  AND (deliveries.next_attempt_at IS NULL OR deliveries.next_attempt_at <= ?)
                ORDER BY deliveries.id
                """,
                (channel, now),
            ).fetchall()

    def recent_messages(self, limit: int = 5) -> list[sqlite3.Row]:
        limit = max(1, min(int(limit), 20))
        with self.connect() as connection:
            return connection.execute(
                "SELECT id, sender, received_at, text FROM messages WHERE sender != 'system' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def delivery_summary(self) -> dict[str, dict[str, int]]:
        summary = {channel: {} for channel in ("telegram", "vk")}
        with self.connect() as connection:
            rows = connection.execute("SELECT channel, status, COUNT(*) AS count FROM deliveries GROUP BY channel, status").fetchall()
        for row in rows:
            summary[row["channel"]][row["status"]] = int(row["count"])
        return summary

    def modem_status_snapshot(self) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT device_available, smsd_running, operator_name, network_code,
                       radio_access_technology, registration_state,
                       packet_registration_state, gprs_registration_state, raw_csq,
                       radio_checked_at, signal_percent, signal_checked_at,
                       sent_count, received_count, failed_count,
                       sim_storage_name, sim_storage_used, sim_storage_capacity,
                       sim_storage_free, sim_storage_percent, sim_storage_checked_at,
                       last_contact_at, last_received_at, updated_at
                FROM modem_status WHERE singleton = 1
                """
            ).fetchone()

    def mark_delivery_sent(self, delivery_id: int) -> None:
        now = utcnow()
        with self.transaction() as connection:
            connection.execute("UPDATE deliveries SET status='sent', attempts=attempts+1, sent_at=?, updated_at=?, last_error=NULL WHERE id=?", (now, now, delivery_id))

    def mark_delivery_failure(self, delivery_id: int, *, kind: str, retry_after_seconds: int | None = None, detail: str | None = None, random_source: random.Random | None = None) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        with self.transaction() as connection:
            row = connection.execute("SELECT attempts FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown delivery {delivery_id}")
            attempts = int(row["attempts"]) + 1
            if kind in {"configuration", "http_400"}:
                status = "configuration_error" if kind == "configuration" else "failed"
                next_attempt = None
            else:
                base = retry_after_seconds if retry_after_seconds is not None else min(300, 2 ** min(attempts, 8))
                rng = random_source or random.SystemRandom()
                delay = max(1, int(base + rng.uniform(0, max(1, base * 0.1))))
                status = "retry"
                next_attempt = (now + timedelta(seconds=delay)).isoformat()
            connection.execute("UPDATE deliveries SET status=?, attempts=?, next_attempt_at=?, last_error=?, updated_at=? WHERE id=?", (status, attempts, next_attempt, (detail or kind)[:200], now.isoformat(), delivery_id))

    def claim_bot_update(self, update_id: int) -> bool:
        with self.transaction() as connection:
            try:
                connection.execute("INSERT INTO bot_updates (update_id, processed_at) VALUES (?, ?)", (update_id, utcnow()))
                return True
            except sqlite3.IntegrityError:
                return False

    def update_modem_status(self, *, device_available: bool, smsd_running: bool, last_contact_at: str | None = None, operator_name: str | None = None, network_code: str | None = None, signal_percent: int | None = None, signal_checked_at: str | None = None, sent_count: int | None = None, received_count: int | None = None, failed_count: int | None = None, last_received_at: str | None = None) -> None:
        now = utcnow()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO modem_status (
                    singleton, device_available, smsd_running, last_contact_at,
                    operator_name, network_code, signal_percent, signal_checked_at,
                    sent_count, received_count,
                    failed_count, last_received_at, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    device_available=excluded.device_available,
                    smsd_running=excluded.smsd_running,
                    last_contact_at=COALESCE(excluded.last_contact_at, modem_status.last_contact_at),
                    operator_name=COALESCE(excluded.operator_name, modem_status.operator_name),
                    network_code=COALESCE(excluded.network_code, modem_status.network_code),
                    signal_percent=COALESCE(excluded.signal_percent, modem_status.signal_percent),
                    signal_checked_at=COALESCE(excluded.signal_checked_at, modem_status.signal_checked_at),
                    sent_count=COALESCE(excluded.sent_count, modem_status.sent_count),
                    received_count=COALESCE(excluded.received_count, modem_status.received_count),
                    failed_count=COALESCE(excluded.failed_count, modem_status.failed_count),
                    last_received_at=COALESCE(excluded.last_received_at, modem_status.last_received_at),
                    updated_at=excluded.updated_at
                """,
                (device_available, smsd_running, last_contact_at, operator_name, network_code, signal_percent, signal_checked_at, sent_count, received_count, failed_count, last_received_at, now),
            )

    def update_radio_status(self, *, operator_name: str | None, network_code: str | None, access_technology: str | None, registration_state: str | None, packet_registration_state: str | None, gprs_registration_state: str | None, raw_csq: int | None, checked_at: str) -> None:
        now = utcnow()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO modem_status (
                    singleton, device_available, smsd_running, operator_name,
                    network_code, radio_access_technology, registration_state,
                    packet_registration_state, gprs_registration_state, raw_csq,
                    radio_checked_at, updated_at
                ) VALUES (1, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    operator_name=excluded.operator_name,
                    network_code=excluded.network_code,
                    radio_access_technology=excluded.radio_access_technology,
                    registration_state=excluded.registration_state,
                    packet_registration_state=excluded.packet_registration_state,
                    gprs_registration_state=excluded.gprs_registration_state,
                    raw_csq=excluded.raw_csq,
                    radio_checked_at=excluded.radio_checked_at,
                    updated_at=excluded.updated_at
                """,
                (operator_name, network_code, access_technology, registration_state, packet_registration_state, gprs_registration_state, raw_csq, checked_at, now),
            )

    def update_sim_storage(self, *, name: str, used: int, capacity: int, free: int, percent: int, checked_at: str) -> None:
        now = utcnow()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO modem_status (
                    singleton, device_available, smsd_running, sim_storage_name,
                    sim_storage_used, sim_storage_capacity, sim_storage_free,
                    sim_storage_percent, sim_storage_checked_at, updated_at
                ) VALUES (1, 0, 0, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    sim_storage_name=excluded.sim_storage_name,
                    sim_storage_used=excluded.sim_storage_used,
                    sim_storage_capacity=excluded.sim_storage_capacity,
                    sim_storage_free=excluded.sim_storage_free,
                    sim_storage_percent=excluded.sim_storage_percent,
                    sim_storage_checked_at=excluded.sim_storage_checked_at,
                    updated_at=excluded.updated_at
                """,
                (name, used, capacity, free, percent, checked_at, now),
            )

    def update_outage(self, unavailable_since: datetime | None) -> str | None:
        now = datetime.now(UTC).replace(microsecond=0)
        with self.transaction() as connection:
            row = connection.execute("SELECT active FROM outage_state WHERE name='modem_network'").fetchone()
            active = bool(row and row["active"])
            sustained = unavailable_since is not None and now - unavailable_since >= timedelta(minutes=5)
            if sustained and not active:
                connection.execute("INSERT INTO outage_state (name, opened_at, active, recovered_at, updated_at) VALUES ('modem_network', ?, 1, NULL, ?) ON CONFLICT(name) DO UPDATE SET opened_at=excluded.opened_at, active=1, recovered_at=NULL, updated_at=excluded.updated_at", (now.isoformat(), now.isoformat()))
                self._create_system_event(connection, "outage_opened", "Сетевой статус модема недоступен более 5 минут", now.isoformat())
                return "outage"
            if unavailable_since is None and active:
                connection.execute("UPDATE outage_state SET active=0, recovered_at=?, updated_at=? WHERE name='modem_network'", (now.isoformat(), now.isoformat()))
                self._create_system_event(connection, "outage_recovered", "Сетевой статус модема восстановлен", now.isoformat())
                return "recovery"
            return None

    def health(self, smsd_running: bool, device_available: bool) -> dict[str, object]:
        with self.connect() as connection:
            queues = {channel: connection.execute("SELECT COUNT(*) FROM deliveries WHERE channel=? AND status IN ('pending', 'retry')", (channel,)).fetchone()[0] for channel in ("telegram", "vk")}
            last_sms = connection.execute("SELECT received_at FROM messages WHERE sender != 'system' ORDER BY id DESC LIMIT 1").fetchone()
        return {"database": "ok", "gammu_smsd": "running" if smsd_running else "not_running", "device_path": "available" if device_available else "unavailable", "queue": queues, "last_received_at": last_sms["received_at"] if last_sms else None}
