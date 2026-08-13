"""Read-only modem snapshots through a controlled Gammu pause."""
from __future__ import annotations

import os
import re
import select
import signal
import termios
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


_CPMS_RE = re.compile(r'"([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)')
_COPS_RE = re.compile(r"\+COPS:\s*(\d+)\s*,\s*(\d+)\s*,\s*(?:\"([^\"]*)\"|([^,\r\n]*))\s*(?:,\s*(\d+))?", re.IGNORECASE)
_CSQ_RE = re.compile(r"\+CSQ:\s*(\d+)\s*,\s*(\d+)", re.IGNORECASE)
_CPMS_LOCK = threading.Lock()

_REGISTRATION_LABELS = {
    0: "не зарегистрирован",
    1: "домашняя сеть",
    2: "поиск сети",
    3: "регистрация запрещена",
    4: "неизвестно",
    5: "роуминг",
}
_ACCESS_TECHNOLOGIES = {
    0: "GSM",
    1: "GSM Compact",
    2: "UTRAN/3G",
    3: "GSM+EDGE",
    4: "UTRAN/HSDPA",
    5: "UTRAN/HSUPA",
    6: "UTRAN/HSPA",
    7: "E-UTRAN/LTE",
}


@dataclass(frozen=True)
class SimStorageStatus:
    name: str
    used: int
    capacity: int
    free: int
    percent: int
    checked_at: str | None = None


@dataclass(frozen=True)
class RadioStatus:
    raw_csq: int | None
    operator_name: str | None
    network_code: str | None
    access_technology: str | None
    registration_state: str | None
    packet_registration_state: str | None
    gprs_registration_state: str | None
    checked_at: str | None = None


@dataclass(frozen=True)
class ModemSnapshot:
    radio: RadioStatus | None
    sim_storage: SimStorageStatus | None


def storage_level(percent: int | None) -> str:
    if percent is None:
        return "нет данных"
    if percent >= 100:
        return "переполнена"
    if percent >= 95:
        return "критично"
    if percent >= 80:
        return "предупреждение"
    return "норма"


def _registration_value(output: str, command: str) -> str | None:
    match = re.search(rf"\+{command}:\s*(?:\d+\s*,\s*)?(\d+)", output, re.IGNORECASE)
    if not match:
        return None
    code = int(match.group(1))
    return f"{_REGISTRATION_LABELS.get(code, 'неизвестно')} ({code})"


def parse_radio_response(output: str) -> RadioStatus | None:
    """Parse read-only CSQ/COPS/registration responses."""
    csq_match = _CSQ_RE.search(output)
    raw_csq = None
    if csq_match:
        candidate = int(csq_match.group(1))
        raw_csq = candidate if 0 <= candidate <= 31 else None

    cops_match = _COPS_RE.search(output)
    operator_name = None
    network_code = None
    access_technology = None
    if cops_match:
        format_code = int(cops_match.group(2))
        operator_name = (cops_match.group(3) or cops_match.group(4) or "").strip() or None
        access_code = cops_match.group(5)
        if access_code is not None:
            access_technology = _ACCESS_TECHNOLOGIES.get(int(access_code), f"код {access_code}")

    registration_state = _registration_value(output, "CREG")
    packet_registration_state = _registration_value(output, "CEREG")
    gprs_registration_state = _registration_value(output, "CGREG")
    if not any((csq_match, cops_match, registration_state, packet_registration_state, gprs_registration_state)):
        return None
    return RadioStatus(
        raw_csq=raw_csq,
        operator_name=operator_name,
        network_code=network_code,
        access_technology=access_technology,
        registration_state=registration_state,
        packet_registration_state=packet_registration_state,
        gprs_registration_state=gprs_registration_state,
    )


def parse_cpms_response(output: str, storage_name: str = "SM") -> SimStorageStatus | None:
    """Parse +CPMS? output and select the requested storage entry."""
    entries = _CPMS_RE.findall(output)
    for name, used_text, capacity_text in entries:
        if name.upper() != storage_name.upper():
            continue
        used = int(used_text)
        capacity = int(capacity_text)
        if capacity < 0 or used < 0 or used > capacity:
            return None
        free = capacity - used
        percent = round(used * 100 / capacity) if capacity else 100
        return SimStorageStatus(
            name=name,
            used=used,
            capacity=capacity,
            free=free,
            percent=min(100, max(0, percent)),
        )
    return None


def _read_response(fd: int, timeout: float) -> str:
    result = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], min(0.5, max(0.1, deadline - time.monotonic())))
        if not ready:
            continue
        try:
            chunk = os.read(fd, 8192)
        except BlockingIOError:
            continue
        if not chunk:
            continue
        result.extend(chunk)
        normalized = bytes(result).replace(b"\r", b"\n")
        if b"\nOK\n" in normalized or b"\nERROR\n" in normalized:
            break
    return result.decode("utf-8", errors="replace")


def _configure_serial(fd: int) -> None:
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[3] = 0
    attrs[4] = termios.B115200
    attrs[5] = termios.B115200
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)


def query_commands(device_path: str | Path, commands: tuple[str, ...], timeout: float = 5.0) -> dict[str, str]:
    fd = os.open(device_path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        _configure_serial(fd)
        responses = {}
        for command in commands:
            os.write(fd, (command + "\r").encode("ascii"))
            responses[command] = _read_response(fd, timeout)
        return responses
    finally:
        os.close(fd)


def _pid_from_file(pid_path: str | Path) -> int:
    pid = int(Path(pid_path).read_text(encoding="ascii").strip())
    if pid <= 1:
        raise ValueError("invalid SMSD pid")
    return pid


def _with_smsd_paused(
    device_path: str | Path,
    query_fn: Callable[[str | Path, float], object],
    smsd_pid_path: str | Path,
    *,
    wait_seconds: float,
    timeout: float,
    signal_fn: Callable[[int, int], None],
    sleep_fn: Callable[[float], None],
):
    pid = _pid_from_file(smsd_pid_path)
    signal_fn(pid, signal.SIGUSR1)
    try:
        sleep_fn(wait_seconds)
        return query_fn(device_path, timeout)
    finally:
        try:
            signal_fn(pid, signal.SIGUSR2)
        except OSError:
            pass


def _timestamped_radio(status: RadioStatus | None) -> RadioStatus | None:
    if status is None:
        return None
    return replace(status, checked_at=datetime.now(UTC).replace(microsecond=0).isoformat())


def _timestamped_sim(status: SimStorageStatus | None) -> SimStorageStatus | None:
    if status is None:
        return None
    return replace(status, checked_at=datetime.now(UTC).replace(microsecond=0).isoformat())


def read_modem_snapshot(
    device_path: str | Path,
    smsd_pid_path: str | Path = "/run/sms-gateway/gammu-smsd.proc",
    *,
    wait_seconds: float = 1.0,
    timeout: float = 5.0,
    signal_fn: Callable[[int, int], None] = os.kill,
    sleep_fn: Callable[[float], None] = time.sleep,
    query_fn: Callable[[str | Path, tuple[str, ...], float], dict[str, str]] = query_commands,
) -> ModemSnapshot:
    """Read radio and SIM storage in one SMSD pause and serial session."""
    with _CPMS_LOCK:
        try:
            responses = _with_smsd_paused(
                device_path,
                lambda device, query_timeout: query_fn(
                    device,
                    ("AT+CSQ", "AT+COPS?", "AT+CREG?", "AT+CEREG?", "AT+CGREG?", "AT+CPMS?"),
                    query_timeout,
                ),
                smsd_pid_path,
                wait_seconds=wait_seconds,
                timeout=timeout,
                signal_fn=signal_fn,
                sleep_fn=sleep_fn,
            )
            radio = _timestamped_radio(parse_radio_response("\n".join(responses.values())))
            sim = _timestamped_sim(parse_cpms_response(responses.get("AT+CPMS?", "")))
            return ModemSnapshot(radio=radio, sim_storage=sim)
        except (OSError, ValueError, TypeError, UnicodeError):
            return ModemSnapshot(radio=None, sim_storage=None)


def read_sim_storage(
    device_path: str | Path,
    smsd_pid_path: str | Path = "/run/sms-gateway/gammu-smsd.proc",
    *,
    wait_seconds: float = 1.0,
    timeout: float = 5.0,
    signal_fn: Callable[[int, int], None] = os.kill,
    sleep_fn: Callable[[float], None] = time.sleep,
    query_fn: Callable[[str | Path, float], str] | None = None,
) -> SimStorageStatus | None:
    """Compatibility wrapper for a CPMS-only snapshot."""
    if query_fn is not None:
        with _CPMS_LOCK:
            try:
                result = _with_smsd_paused(device_path, query_fn, smsd_pid_path, wait_seconds=wait_seconds, timeout=timeout, signal_fn=signal_fn, sleep_fn=sleep_fn)
                return _timestamped_sim(parse_cpms_response(result))
            except (OSError, ValueError, TypeError, UnicodeError):
                return None
    return read_modem_snapshot(device_path, smsd_pid_path, wait_seconds=wait_seconds, timeout=timeout, signal_fn=signal_fn, sleep_fn=sleep_fn).sim_storage


def read_radio_status(
    device_path: str | Path,
    smsd_pid_path: str | Path = "/run/sms-gateway/gammu-smsd.proc",
    *,
    wait_seconds: float = 1.0,
    timeout: float = 5.0,
    signal_fn: Callable[[int, int], None] = os.kill,
    sleep_fn: Callable[[float], None] = time.sleep,
    query_fn: Callable[[str | Path, float], RadioStatus | None] | None = None,
) -> RadioStatus | None:
    """Compatibility wrapper for a radio-only snapshot."""
    if query_fn is not None:
        with _CPMS_LOCK:
            try:
                result = _with_smsd_paused(device_path, query_fn, smsd_pid_path, wait_seconds=wait_seconds, timeout=timeout, signal_fn=signal_fn, sleep_fn=sleep_fn)
                return _timestamped_radio(result)
            except (OSError, ValueError, TypeError, UnicodeError):
                return None
    return read_modem_snapshot(device_path, smsd_pid_path, wait_seconds=wait_seconds, timeout=timeout, signal_fn=signal_fn, sleep_fn=sleep_fn).radio
