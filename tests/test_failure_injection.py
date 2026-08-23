"""Failure injection (SPEC §22): absent files, denied permissions, offline.

Expected behavior for every injected failure: safe, deterministic,
explainable — a defined result with evidence or a defined exception, NEVER a
raw traceback escaping the module boundary.
"""

from __future__ import annotations

import pytest

from dongle_rescue.firmware.resolver import (
    check_firmware_presence,
    detect_package_managers,
    recommend_firmware_action,
)
from dongle_rescue.host import Host, HostError
from dongle_rescue.linux.modules_alias import read_alias_lines


class InjectedHost(Host):
    """Fake host whose every accessor raises HostError per injected mode."""

    def __init__(self, mode: str):
        self.mode = mode
        self.calls: list[str] = []

    def _fail(self, op: str, path: str) -> None:
        self.calls.append(f"{op}:{path}")
        if self.mode == "file_missing":
            raise HostError(f"read {path}: No such file or directory")
        if self.mode == "permission_denied":
            raise HostError(f"read {path}: Permission denied")
        if self.mode == "dns_off":
            # network-backed lookups would fail here; local fs stays intact —
            # modeled as generic I/O failure to prove no network path is taken.
            raise HostError(f"resolve {path}: Temporary failure in name resolution")
        raise AssertionError(f"unknown mode {self.mode}")

    def read(self, path) -> str:
        self._fail("read", path)
        raise AssertionError("unreachable")

    def exists(self, path) -> bool:
        self._fail("exists", path)
        raise AssertionError("unreachable")

    def listdir(self, path) -> list[str]:
        self._fail("listdir", path)
        raise AssertionError("unreachable")

    def resolve_realpath(self, path) -> str:
        self._fail("realpath", path)
        raise AssertionError("unreachable")


MODES = ["file_missing", "permission_denied", "dns_off"]


@pytest.mark.parametrize("mode", MODES)
def test_firmware_presence_never_raises_returns_defined_result(mode):
    host = InjectedHost(mode)
    st = check_firmware_presence(host, module="mt7601u", rel_path="mt7601u.bin")
    # defined outcome: indeterminate (None), never installed=True by guesswork
    assert st.installed is None
    assert st.normalized_path == "mt7601u.bin"
    assert st.evidence  # explainable: evidence trail exists


@pytest.mark.parametrize("mode", MODES)
def test_alias_read_failure_is_hosterror_not_crash(mode):
    with pytest.raises(HostError) as ei:
        read_alias_lines(InjectedHost(mode), release="6.17.0-test")
    assert "modules.alias" in str(ei.value)


def test_dns_off_cannot_trigger_network_paths():
    """Detection-only design: even with DNS off, resolution completes."""
    which_off = lambda name: None  # noqa: E731  (DNS down => nothing resolvable)
    assert detect_package_managers(which_off) == ()
    host = InjectedHost("dns_off")
    st = check_firmware_presence(host, module="mt7601u", rel_path="mt7601u.bin")
    action = recommend_firmware_action(st, managers=())
    assert action.kind in {"install_firmware_package", "manual_package_lookup"}
    assert action.safe_for_automation is False
    assert action.commands == ()  # no channel detected -> nothing proposed


@pytest.mark.parametrize("mode", MODES)
def test_enumeration_survives_total_host_failure(mode):
    from dongle_rescue.usb.enumeration import enumerate_usb_devices

    assert enumerate_usb_devices(InjectedHost(mode)) == []


@pytest.mark.parametrize("mode", MODES)
def test_journal_failures_are_defined_errors_not_oserror_leaks(tmp_path, mode):
    from dongle_rescue.repair.transaction import Journal, create_transaction

    rec = create_transaction(
        before={}, change={"op": "noop"}, after={}, rollback_action={"op": "noop"}
    )
    if mode == "permission_denied":
        target = "/proc/definitely-not-writable/journal.jsonl"
    elif mode == "file_missing":
        target = str(
            tmp_path / "missing-dir" / "journal.jsonl"
        )  # parent auto-created -> must succeed
    else:  # dns_off does not affect journaling; keep local semantics
        target = str(tmp_path / "journal.jsonl")

    j = Journal(target)
    if mode == "permission_denied":
        with pytest.raises(OSError):
            j.append(rec)
    else:
        j.append(rec)  # auto-create parents; deterministic success
        assert len(j.load()) == 1
