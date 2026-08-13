"""Read-only status from the running gammu-smsd shared memory monitor."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class GammuStatus:
    sent: int | None
    received: int | None
    failed: int | None
    battery: int | None
    signal_percent: int | None
    checked_at: str


def _integer(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_monitor_csv(output: str) -> GammuStatus | None:
    """Parse Gammu monitor CSV, tolerating the version-specific prefix fields."""
    for raw_line in reversed(output.splitlines()):
        line = raw_line.strip()
        if not line or ";" not in line:
            continue
        fields = line.split(";")
        if len(fields) < 6 or fields[0].lower() == "client":
            continue
        # Gammu 1.42 may prepend version/phone metadata. The final five fields
        # are always sent, received, failed, battery and signal.
        sent, received, failed, battery, signal = fields[-5:]
        return GammuStatus(
            sent=_integer(sent),
            received=_integer(received),
            failed=_integer(failed),
            battery=_integer(battery),
            signal_percent=_integer(signal),
            checked_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
    return None


def read_gammu_status(config_path: str | Path = "/run/sms-gateway/gammu-smsdrc") -> GammuStatus | None:
    try:
        result = subprocess.run(
            ["gammu-smsd-monitor", "-C", "-L", "-n", "1", "-d", "0", "-c", str(config_path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_monitor_csv(result.stdout + "\n" + result.stderr)
