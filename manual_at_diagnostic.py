#!/usr/bin/env python3
import os
import re
import select
import termios
import time

DEVICE = "/dev/huawei-e3272-sms"
COMMANDS = (
    "AT",
    "ATI",
    "AT+CPIN?",
    "AT+CSQ",
    "AT+COPS?",
    "AT+CREG?",
    "AT+CEREG?",
    "AT+CGREG?",
    "AT+CGATT?",
    "AT+CSCA?",
    "AT+CPMS?",
    "AT+CMGF?",
    "AT+CSMS?",
    "AT+CNMI?",
    "AT^SYSINFOEX",
    "AT^HCSQ?",
)


def mask_sensitive(text: str) -> str:
    patterns = (
        r"(?i)(IMEI[^0-9]*)([0-9]{8,})",
        r"(?i)(IMSI[^0-9]*)([0-9]{8,})",
        r"(?i)(ICCID[^0-9]*)([0-9]{10,})",
    )
    for pattern in patterns:
        text = re.sub(pattern, r"\1<redacted>", text)
    return text


def read_response(fd: int, timeout: float = 5.0) -> str:
    result = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.5)
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


fd = os.open(DEVICE, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
try:
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

    os.write(fd, b"AT\r")
    time.sleep(0.3)
    read_response(fd, 2)

    for command in COMMANDS:
        os.write(fd, (command + "\r").encode("ascii"))
        response = read_response(fd)
        print(f">>> {command}")
        print(mask_sensitive(response).strip())
        print()
finally:
    os.close(fd)
