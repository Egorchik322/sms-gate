from __future__ import annotations

import csv
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path


@dataclass(frozen=True)
class GammuStatus:
    client: str
    phone_id: str
    imei: str
    sent: int
    received: int
    failed: int
    battery_percent: int | None
    signal_percent: int | None
    checked_at: str

    @property
    def battery(self) -> int | None:
        return self.battery_percent


def _number(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _signal(value: str) -> int | None:
    parsed = _number(value)
    if parsed is None or parsed < 0 or parsed > 100:
        return None
    # Huawei E3272 LTE firmware can report monitor signal as 0 while direct
    # AT+CSQ still reports usable radio. Do not present that as 0/100.
    return parsed or None


def parse_monitor_csv(output: str, checked_at: str | None = None) -> GammuStatus | None:
    rows = list(csv.reader(StringIO(output), delimiter=";"))
    if not rows:
        return None
    checked_at = checked_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    for row in reversed(rows):
        if len(row) == 9:
            # Gammu 1.42 may prefix the data with a client banner and an
            # extra metadata column on the same CSV record.
            client = row[0]
            phone_id, imei = row[1], row[2]
            offset = 1
        elif len(row) == 8:
            client = row[0]
            phone_id, imei = row[1], row[2]
            offset = 0
        else:
            continue
        if client.strip().lower() in {"client", "gammu"} and row[3 + offset].lower() == "sent":
            continue
        sent = _number(row[3 + offset])
        received = _number(row[4 + offset])
        failed = _number(row[5 + offset])
        battery = _number(row[6 + offset])
        signal = _signal(row[7 + offset])
        if sent is None or received is None or failed is None:
            continue
        return GammuStatus(
            client=client,
            phone_id=phone_id,
            imei=imei,
            sent=sent,
            received=received,
            failed=failed,
            battery_percent=battery,
            signal_percent=signal,
            checked_at=checked_at,
        )
    return None


def read_gammu_status(config_path: str | Path) -> GammuStatus | None:
    try:
        result = subprocess.run(
            ["gammu-smsd-monitor", "-C", "-L", "-n", "1", "-d", "0", "-c", str(config_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_monitor_csv(result.stdout, datetime.now(UTC).replace(microsecond=0).isoformat())
