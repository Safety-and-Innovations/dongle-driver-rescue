"""Deterministic filesystem abstraction.

Every module that touches the host (sysfs, /proc, /lib/firmware, module tree)
goes through this protocol, so tests run against synthetic fixtures instead of
real hardware and failure injection is a constructor argument (SPEC §20-§22).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class HostError(Exception):
    """Raised when the underlying host access fails in a defined way."""


class Host:
    """Read/write surface over the real machine. Subclass or fake in tests."""

    def read(self, path: str) -> str:
        raise NotImplementedError

    def exists(self, path: str) -> bool:
        raise NotImplementedError

    def listdir(self, path: str) -> list[str]:
        raise NotImplementedError

    def resolve_realpath(self, path: str) -> str:
        """Return symlink-free absolute path; must stay under expected root."""
        raise NotImplementedError

    def sha256(self, path: str) -> str | None:
        """Hash of file content, or None when absent/unreadable."""
        raise NotImplementedError

    # ---- privileged operations (repair path; ADR 0002 S5) ----

    def write_driver_new_id(self, driver: str, vid_pid: str) -> None:
        raise NotImplementedError

    def modprobe(self, *args: str) -> tuple[int, str]:
        raise NotImplementedError

    def append_modprobe_d(self, filename: str, content: str) -> str:
        raise NotImplementedError


class RealHost(Host):
    """Production implementation. All paths resolved against real roots."""

    def __init__(self, *, firmware_root: str = "/lib/firmware") -> None:
        self._firmware_root = os.path.realpath(firmware_root)

    def read(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError as exc:
            raise HostError(f"read {path}: {exc}") from exc

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def listdir(self, path: str) -> list[str]:
        try:
            entries = sorted(os.listdir(path))  # stable order (ADR 0003 D4)
        except OSError as exc:
            raise HostError(f"listdir {path}: {exc}") from exc
        return entries

    def resolve_realpath(self, path: str) -> str:
        real = os.path.realpath(path)
        return real

    def sha256(self, path: str) -> str | None:
        if not os.path.isfile(path):
            return None
        h = hashlib.sha256()
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    def write_driver_new_id(self, driver: str, vid_pid: str) -> None:
        raise NotImplementedError("privileged write implemented in repair module")

    def modprobe(self, *args: str) -> tuple[int, str]:
        raise NotImplementedError("privileged op implemented in repair module")

    def append_modprobe_d(self, filename: str, content: str) -> str:
        raise NotImplementedError("privileged op implemented in repair module")


def firmware_exists(host: Host, rel_path: str) -> bool | None:
    """Check a validated firmware relative path under the firmware root.

    Symlink-safe per ADR 0002 S3: realpath must remain under the root.
    Returns None when existence cannot be determined.
    """
    from .types import require_firmware_path

    try:
        rel = require_firmware_path(rel_path)
    except ValueError:
        return False  # invalid by grammar -> treated as not present, flagged upstream
    root = Path("/lib/firmware")
    target = root / rel
    try:
        real = os.path.realpath(target)
    except OSError:
        return None
    if os.path.commonpath([real, str(root)]) != str(root):
        return False  # escapes root: refuse silently? No — caller records evidence.
    return os.path.exists(real)
