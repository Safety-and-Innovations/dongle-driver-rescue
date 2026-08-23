"""Fixture tree for SPEC §20/§22 — provenance-cited, no physical hardware.

Every file here states which research document it derives from. The
FixtureRootHost maps virtual absolute paths (/sys/..., /lib/firmware/...)
into this directory so tests exercise the same code paths as RealHost.
"""

from __future__ import annotations

import os

import pytest

from dongle_rescue.host import Host, HostError

FIXTURES = os.path.dirname(__file__)
FIXTURE_ROOT = os.path.join(FIXTURES, "tree")


class FixtureRootHost(Host):
    """Host over a real directory; virtual roots map into FIXTURE_ROOT.

    /sys/bus/usb/devices -> tree/sys/bus/usb/devices
    /lib/firmware        -> tree/lib/firmware
    /lib/modules/<rel>   -> tree/lib/modules/<rel>
    Anything resolving outside the fixture root does not exist (deterministic;
    symlink escapes are refused by the S3 check upstream of us).
    """

    _MAP = {
        "/sys/": "sys/",
        "/lib/firmware": "lib/firmware",
        "/lib/modules": "lib/modules",
    }

    def __init__(self, root: str | None = None):
        self._root = root or FIXTURE_ROOT
        # scenario name is appended by the factory fixture via chdir-free path
        self._scenario: str | None = None

    def use_scenario(self, name: str) -> None:
        self._scenario = name

    def _map(self, path: str) -> str:
        p = os.path.normpath(path)
        if self._scenario:
            base = os.path.join(self._root, self._scenario)
        else:
            base = self._root
        for vroot, sub in self._MAP.items():
            if p.startswith(vroot):
                return os.path.join(base, sub + p[len(vroot):])
        raise HostError(f"path outside fixture roots: {path}")

    def read(self, path: str) -> str:
        mp = self._map(path)
        try:
            with open(mp, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError as exc:
            raise HostError(f"read {path}: {exc}") from exc

    def exists(self, path: str) -> bool:
        try:
            return os.path.exists(self._map(path))
        except HostError:
            return False

    def listdir(self, path: str) -> list[str]:
        mp = self._map(path)
        try:
            return sorted(os.listdir(mp))
        except OSError as exc:
            raise HostError(f"listdir {path}: {exc}") from exc

    def resolve_realpath(self, path: str) -> str:
        mp = self._map(path)
        real = os.path.realpath(mp)
        root_real = os.path.realpath(self._root)
        if not (real == root_real or real.startswith(root_real + os.sep)):
            return path  # escape attempt: report the virtual path; exists()=False
        # Re-express the realpath as a VIRTUAL absolute path so callers can
        # feed it back into read/exists (bound_driver does exactly that).
        scenario_prefix = os.path.join(root_real, self._scenario or "")
        rel = os.path.relpath(real, scenario_prefix)
        return "/" + rel.replace(os.sep, "/")


@pytest.fixture()
def scenario_host():
    """Parametrizable host bound to one scenario under tests/fixtures/tree."""
    host = FixtureRootHost()

    def _use(name: str) -> FixtureRootHost:
        host.use_scenario(name)
        return host

    return _use


def load_text(*parts: str) -> str:
    with open(os.path.join(FIXTURES, *parts), encoding="utf-8") as fh:
        return fh.read()


DMESG_FW_MISSING_RTL8188EU = [
    "[    8.901] usb 1-2: rtl8xxxu 1-2:1.0: Direct firmware load for "
    "rtlwifi/rtl8188eufw.bin failed with error -2",
    "[    8.912] usb 1-2: Failed to request firmware rtlwifi/rtl8188eufw.bin (-2)",
]

DMESG_DESCRIPTOR_ERROR = [
    "[    3.500000] usb 1-2: device descriptor read/64, error -71",
    "[    3.610000] usb 1-2: device descriptor read/all, error -71",
]

# Secure Boot rejection shape — messages confirmed from upstream source
# (security/lockdown/lockdown.c, kernel/module/signing.c, kernel/module/main.c).
# Valid across kernels 5.15..6.17; string literals unchanged.
DMESG_SECURE_BOOT_REJECTION = [
    # Lockdown path (CONFIG_LOCK_DOWN_IN_EFI_SECURE_BOOT=y, distro default e.g. Ubuntu/Debian):
    "[   12.0] Lockdown: modprobe: unsigned module loading is restricted; see man kernel_lockdown.7",
    # Taint path (MODULE_SIG_FORCE=n or sig_enforce=0):
    "[   12.0] rtl88xxau: module verification failed: signature and/or "
    "required key missing - tainting kernel",
    # Enforcement path (MODULE_SIG_FORCE=y):
    "[   12.0] Loading of unsigned module is rejected",
]
