"""Gateway runtime: durable ingress, independent delivery, and Telegram control."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

from .config import ConfigurationError, Settings
from .control import TelegramControl
from .cpms import read_modem_snapshot
from .delivery import DeliveryWorker
from .gammu_c_status import read_c_status
from .gammu_shared_status import read_shared_status
from .gammu_status import read_gammu_status
from .http_transports import ProxyJsonPoster, TelegramTransport, VkTransport
from .ingress import FilesIngress
from .polling import TelegramPoller
from .store import GatewayStore, parse_timestamp

LOGGER = logging.getLogger("sms_gateway")
STOP = False
DEFAULT_MODEM_STATUS_INTERVAL = 300


def stop_handler(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def process_is_running(path: str | Path) -> bool:
    try:
        pid = int(Path(path).read_text(encoding="ascii").strip())
        os.kill(pid, 0)
    except (OSError, ValueError, UnicodeError):
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SMS gateway runtime")
    parser.add_argument("--once", action="store_true", help="ingest and process queues once")
    parser.add_argument("--interval", type=int, default=15, help="poll interval in seconds")
    parser.add_argument("--health", action="store_true", help="print health and exit")
    return parser


def configure_workers(settings: Settings, store: GatewayStore) -> list[DeliveryWorker]:
    workers: list[DeliveryWorker] = []
    try:
        workers.append(DeliveryWorker(store, TelegramTransport(settings)))
    except ConfigurationError:
        LOGGER.error("channel configuration error channel=telegram class=configuration_error")
        for row in store.due_deliveries("telegram"):
            store.mark_delivery_failure(row["id"], kind="configuration", detail="telegram_configuration")
    try:
        workers.append(DeliveryWorker(store, VkTransport(settings)))
    except ConfigurationError:
        LOGGER.error("channel configuration error channel=vk class=configuration_error")
        for row in store.due_deliveries("vk"):
            store.mark_delivery_failure(row["id"], kind="configuration", detail="vk_configuration")
    return workers


def configure_poller(settings: Settings, store: GatewayStore) -> TelegramPoller | None:
    try:
        settings.require_telegram()
        control = TelegramControl(store, settings.telegram_allowed_user_ids, settings.telegram_chat_id, settings.modem_reregistration_enabled)
        return TelegramPoller(settings, control, poster=ProxyJsonPoster(settings))
    except ConfigurationError:
        LOGGER.error("telegram polling unavailable class=configuration_error")
        return None


def stored_outage_start(store: GatewayStore) -> datetime | None:
    with store.connect() as connection:
        row = connection.execute("SELECT opened_at, active FROM outage_state WHERE name='modem_network'").fetchone()
    if row and row["active"] and row["opened_at"]:
        return parse_timestamp(row["opened_at"])
    return None


def latest_received_at(store: GatewayStore) -> str | None:
    with store.connect() as connection:
        row = connection.execute("SELECT received_at FROM messages WHERE sender != 'system' ORDER BY id DESC LIMIT 1").fetchone()
    return row["received_at"] if row else None


def run(settings: Settings, *, once: bool = False, interval: int = 15) -> None:
    store = GatewayStore(settings.database_path)
    store.initialize()
    ingress = FilesIngress(store, settings.inbox_path, settings.archive_path)
    workers = configure_workers(settings, store)
    poller = configure_poller(settings, store)
    unavailable_since = stored_outage_start(store)
    monitor_config = os.environ.get("GAMMU_CONFIG", "/run/sms-gateway/gammu-smsdrc")
    modem_device = os.environ.get("MODEM_DEVICE", "/dev/huawei-e3272-sms")
    modem_status_interval = max(60, int(os.environ.get("MODEM_STATUS_CHECK_INTERVAL_SECONDS", DEFAULT_MODEM_STATUS_INTERVAL)))
    at_snapshot_enabled = os.environ.get("MODEM_STATUS_AT_ENABLED", "false").lower() == "true"
    next_modem_status_check = time.monotonic() + min(30, modem_status_interval)

    while not STOP:
        ids = ingress.ingest_pending()
        if ids:
            LOGGER.info("ingested message_count=%s", len(ids))
        for worker in workers:
            worker.run_once()
        if poller is not None and not once:
            poller.poll_once()

        device_available = Path(modem_device).exists()
        smsd_running = process_is_running("/run/sms-gateway/gammu-smsd.proc")
        c_status = read_c_status(monitor_config) if smsd_running else None
        shared_status = read_shared_status(monitor_config) if smsd_running and c_status is None else None
        monitor_status = read_gammu_status(monitor_config) if smsd_running and c_status is None and shared_status is None else None

        if c_status is not None:
            signal_percent, sent_count, received_count, failed_count = c_status.signal_percent, c_status.sent, c_status.received, c_status.failed
            operator_name, network_code, checked_at = c_status.network_name, c_status.network_code, c_status.checked_at
        elif shared_status is not None:
            signal_percent, sent_count, received_count, failed_count = shared_status.signal_percent, shared_status.sent, shared_status.received, shared_status.failed
            operator_name, network_code, checked_at = shared_status.network_name, shared_status.network_code, shared_status.checked_at
        else:
            signal_percent = monitor_status.signal_percent if monitor_status else None
            sent_count = monitor_status.sent if monitor_status else None
            received_count = monitor_status.received if monitor_status else None
            failed_count = monitor_status.failed if monitor_status else None
            operator_name = network_code = None
            checked_at = monitor_status.checked_at if monitor_status else None

        store.update_modem_status(device_available=device_available, smsd_running=smsd_running, last_contact_at=checked_at, operator_name=operator_name, network_code=network_code, signal_percent=signal_percent, signal_checked_at=checked_at, sent_count=sent_count, received_count=received_count, failed_count=failed_count, last_received_at=latest_received_at(store))
        if c_status is not None:
            store.update_c_status(signal_percent=c_status.signal_percent, signal_dbm=c_status.signal_dbm, bit_error_percent=c_status.bit_error_percent, sent=c_status.sent, received=c_status.received, failed=c_status.failed, network_name=c_status.network_name, network_code=c_status.network_code, network_state=c_status.network_state, lac=c_status.lac, cid=c_status.cid, gprs_state=c_status.gprs_state, packet_state=c_status.packet_state, packet_lac=c_status.packet_lac, packet_cid=c_status.packet_cid, checked_at=c_status.checked_at)

        if not once and at_snapshot_enabled and device_available and smsd_running and time.monotonic() >= next_modem_status_check:
            snapshot = read_modem_snapshot(modem_device)
            next_modem_status_check = time.monotonic() + modem_status_interval
            if snapshot.radio is not None:
                radio = snapshot.radio
                store.update_radio_status(operator_name=radio.operator_name, network_code=radio.network_code, access_technology=radio.access_technology, registration_state=radio.registration_state, packet_registration_state=radio.packet_registration_state, gprs_registration_state=radio.gprs_registration_state, raw_csq=radio.raw_csq, checked_at=radio.checked_at or datetime.now(UTC).replace(microsecond=0).isoformat())
            if snapshot.sim_storage is not None:
                sim = snapshot.sim_storage
                store.update_sim_storage(name=sim.name, used=sim.used, capacity=sim.capacity, free=sim.free, percent=sim.percent, checked_at=sim.checked_at or datetime.now(UTC).replace(microsecond=0).isoformat())

        unavailable_since = None if device_available and smsd_running else unavailable_since or datetime.now(UTC).replace(microsecond=0)
        event = store.update_outage(unavailable_since)
        if event:
            LOGGER.warning("modem outage state changed class=%s", event)
        if once:
            return
        time.sleep(max(1, interval))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    args = build_parser().parse_args(argv)
    settings = Settings.from_environment()
    store = GatewayStore(settings.database_path)
    store.initialize()
    if args.health:
        print(store.health(smsd_running=process_is_running("/run/sms-gateway/gammu-smsd.proc"), device_available=Path(os.environ.get("MODEM_DEVICE", "/dev/huawei-e3272-sms")).exists()))
        return 0
    run(settings, once=args.once, interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
