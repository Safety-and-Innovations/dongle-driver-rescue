"""TDD: log access plan + reboot-pending detector.

Facts CONFIRMED on this host (Ubuntu 24.04 arm64, user 'ubuntu' in 'adm'):
- dmesg_restrict=1 → dmesg(1) fails "Operation not permitted" exit 1
- journalctl -k works (exit 0) for adm/systemd-journal members
- /lib/modules may hold kernels newer than uname -r → reboot pending
"""

from __future__ import annotations

from dongle_rescue.host import Host, HostError
from dongle_rescue.linux.log_access import (
    plan_kernel_log_access,
    DMESG_ARGV,
    JOURNALCTL_ARGV,
    reboot_pending,
)


class MapHost(Host):
    """Minimal dict-backed host."""

    def __init__(self, files=None, dirs=None):
        self.files = set(files or [])
        self.dirs = {k: list(v) for k, v in (dirs or {}).items()}

    def read(self, path):
        if path in self.files:
            return ""
        raise HostError(f"read {path}: No such file")

    def exists(self, path):
        return path in self.files or path in self.dirs

    def listdir(self, path):
        if path in self.dirs:
            return list(self.dirs[path])
        raise HostError(f"listdir {path}: No such file")

    def resolve_realpath(self, path):
        return path


def test_journalctl_argv_is_shell_false_safe():
    assert JOURNALCTL_ARGV == ["/usr/bin/journalctl", "-k", "--no-pager", "-o", "short"]
    assert DMESG_ARGV == ["/usr/bin/dmesg"]
    for argv in (JOURNALCTL_ARGV, DMESG_ARGV):
        assert all(isinstance(a, str) for a in argv)
        assert " " not in " ".join(argv).split("/usr/bin/", 1)[0]


def test_reboot_pending_when_newer_kernel_installed():
    host = MapHost(
        files=["/var/run/reboot-required"],
        dirs={"/lib/modules": ["6.17.0-1018-oracle", "6.17.0-1020-oracle"]},
    )
    pending, why = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is True
    assert "1020" in why and "newer" in why


def test_not_pending_when_running_is_newest():
    host = MapHost(dirs={"/lib/modules": ["6.17.0-1018-oracle"]})
    pending, why = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is False
    assert "newest" in why


def test_marker_alone_counts_as_pending():
    host = MapHost(files=["/var/run/reboot-required"],
                   dirs={"/lib/modules": []})
    pending, why = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is True
    assert "reboot-required" in why


def test_older_kernels_do_not_trigger_pending():
    host = MapHost(dirs={"/lib/modules": ["6.17.0-1018-oracle",
                                          "6.17.0-1017-oracle"]})
    pending, _ = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is False


def test_unreadable_modules_dir_is_unknown_never_false():
    host = MapHost()  # nothing readable
    pending, why = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is None
    assert why


def test_non_comparable_release_strings_never_claim_newer():
    host = MapHost(dirs={"/lib/modules": ["weird-custom-build"]})
    pending, _ = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is False  # conservative: no false positive


# ---------------------------------------------------------------------------
# plan_kernel_log_access: formerly `collect_kernel_log`, which promised to
# collect the log and returned None on every path. It was never called by
# production or tests — coverage showed the lines never executing. Now
# `doctor` uses it, and these tests pin the contract.
# ---------------------------------------------------------------------------


class _FakeHost:
    """Minimal host: decides whether journalctl exists and records queries."""

    def __init__(self, with_journalctl: bool):
        self.with_journalctl = with_journalctl
        self.queried: list[str] = []

    def exists(self, path):
        self.queried.append(path)
        return self.with_journalctl and path == "/usr/bin/journalctl"

    def read(self, path):
        raise AssertionError("the planner must not READ anything, only plan")

    def listdir(self, path):
        raise AssertionError("the planner must not list anything")

    def resolve_realpath(self, path):
        return path


def test_plan_uses_journalctl_when_available():
    host = _FakeHost(with_journalctl=True)

    has_it, plan = plan_kernel_log_access(host, release="6.17.0-1018-oracle")

    assert has_it is True
    assert "journalctl" in plan
    assert "6.17.0-1018-oracle" in plan
    # the fallback stays described, with the exact denial symptom
    assert "dmesg" in plan
    assert "Operation not permitted" in plan


def test_plan_falls_back_to_dmesg_without_journalctl():
    host = _FakeHost(with_journalctl=False)

    has_it, plan = plan_kernel_log_access(host, release="6.17.0-1018-oracle")

    assert has_it is False
    assert "dmesg" in plan
    assert "not found" in plan


def test_planner_executes_nothing_and_reads_nothing():
    """SPEC 37: the pure core spawns no processes and reads no files here."""
    host = _FakeHost(with_journalctl=True)

    plan_kernel_log_access(host, release="6.17.0-1018-oracle")

    # had it read anything, _FakeHost would have raised AssertionError
    assert host.queried == ["/usr/bin/journalctl"]


def test_plan_tolerates_failing_host():
    class BrokenHost(_FakeHost):
        def exists(self, path):
            raise OSError("filesystem unavailable")

    has_it, plan = plan_kernel_log_access(BrokenHost(True), release="6.1.0")

    assert has_it is False
    assert "dmesg" in plan
