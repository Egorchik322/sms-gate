"""Read status from an already running Gammu SMSD shared-memory segment."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SharedGammuStatus:
    client: str | None
    phone_id: str | None
    imei: str | None
    sent: int | None
    received: int | None
    failed: int | None
    battery_percent: int | None
    signal_percent: int | None
    network_name: str | None
    network_code: str | None
    net_info: Any
    checked_at: str


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _signal(value: Any) -> int | None:
    parsed = _int(value)
    if parsed is None or parsed <= 0 or parsed > 100:
        return None
    return parsed


def normalize_status(status: dict[str, Any], checked_at: str | None = None) -> SharedGammuStatus:
    network = status.get("Network")
    network_name = _text(status.get("NetworkName"))
    network_code = _text(status.get("NetworkCode"))
    if isinstance(network, dict):
        network_name = network_name or _text(network.get("Name")) or _text(network.get("NetworkName"))
        network_code = network_code or _text(network.get("Code")) or _text(network.get("NetworkCode"))
    elif isinstance(network, str):
        network_name = network_name or _text(network)

    return SharedGammuStatus(
        client=_text(status.get("Client")),
        phone_id=_text(status.get("PhoneID")),
        imei=_text(status.get("IMEI")),
        sent=_int(status.get("Sent")),
        received=_int(status.get("Received")),
        failed=_int(status.get("Failed")),
        battery_percent=_int(status.get("BatteryPercent", status.get("Battery"))),
        signal_percent=_signal(status.get("NetworkSignal", status.get("Signal"))),
        network_name=network_name,
        network_code=network_code,
        net_info=status.get("NetInfo"),
        checked_at=checked_at or datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def read_shared_status(config_path: str | Path) -> SharedGammuStatus | None:
    """Read SMSD shared memory only; never opens the modem device."""
    try:
        import gammu.smsd

        status = gammu.smsd.SMSD(str(config_path)).GetStatus()
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return None
    if not isinstance(status, dict):
        return None
    return normalize_status(status)
