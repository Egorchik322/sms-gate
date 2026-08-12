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
from .delivery import DeliveryWorker
from .http_transports import ProxyJsonPoster, TelegramTransport, VkTransport
from .ingress import FilesIngress
from .polling import TelegramPoller
from .store import GatewayStore, parse_timestamp

LOGGER = logging.getLogger("sms_gateway")
STOP = False


def stop_handler(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


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
        control = TelegramControl(
            store,
            settings.telegram_allowed_user_ids,
            settings.telegram_chat_id,
            settings.modem_reregistration_enabled,
        )
        return TelegramPoller(settings, control, poster=ProxyJsonPoster(settings))
    except ConfigurationError:
        LOGGER.error("telegram polling unavailable class=configuration_error")
        return None


def stored_outage_start(store: GatewayStore) -> datetime | None:
    with store.connect() as connection:
        row = connection.execute(
            "SELECT opened_at, active FROM outage_state WHERE name='modem_network'"
        ).fetchone()
    if row and row["active"] and row["opened_at"]:
        return parse_timestamp(row["opened_at"])
    return None


def run(settings: Settings, *, once: bool = False, interval: int = 15) -> None:
    store = GatewayStore(settings.database_path)
    store.initialize()
    ingress = FilesIngress(store, settings.inbox_path, settings.archive_path)
    workers = configure_workers(settings, store)
    poller = configure_poller(settings, store)
    unavailable_since = stored_outage_start(store)

    while not STOP:
        ids = ingress.ingest_pending()
        if ids:
            LOGGER.info("ingested message_count=%s", len(ids))

        for worker in workers:
            worker.run_once()

        if poller is not None and not once:
            poller.poll_once()

        device_available = Path(
            os.environ.get("MODEM_DEVICE", "/dev/huawei-e3272-sms")
        ).exists()
        smsd_running = Path("/run/sms-gateway/gammu-smsd.proc").exists()
        store.update_modem_status(
            device_available=device_available,
            smsd_running=smsd_running,
        )

        if device_available and smsd_running:
            unavailable_since = None
        elif unavailable_since is None:
            unavailable_since = datetime.now(UTC).replace(microsecond=0)

        event = store.update_outage(unavailable_since)
        if event:
            LOGGER.warning("modem outage state changed class=%s", event)

        if once:
            return
        time.sleep(max(1, interval))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    args = build_parser().parse_args(argv)
    settings = Settings.from_environment()
    store = GatewayStore(settings.database_path)
    store.initialize()

    if args.health:
        print(
            store.health(
                smsd_running=Path("/run/sms-gateway/gammu-smsd.proc").exists(),
                device_available=Path(
                    os.environ.get("MODEM_DEVICE", "/dev/huawei-e3272-sms")
                ).exists(),
            )
        )
        return 0

    run(settings, once=args.once, interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
