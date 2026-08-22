"""Firmware resolution (SPEC §9, state C) — TDD against synthetic hosts.

Evidence rules (ADR 0003 D1): every returned fact carries Evidence citing its
source. The dmesg failure pattern is CONFIRMED in docs/research/linux-kernel.md
§6 ("Direct firmware load for %s failed with error %d", fw_main.c:903).
Package mapping comes exclusively from data/chipsets.json (fw_package_debian),
verified against real .debs per docs/research/mediatek-atheros.md §6.
"""

from __future__ import annotations

import os

import pytest

from dongle_rescue.host import Host, HostError
from dongle_rescue.types import Confidence, RecommendedAction
from dongle_rescue.firmware.resolver import (
    FirmwareFailure,
    FirmwareStatus,
    build_install_command,
    check_firmware_presence,
    detect_package_managers,
    map_firmware_to_packages,
    parse_dmesg_firmware_failures,
    recommend_firmware_action,
)


class FakeHost(Host):
    """In-memory host: files dict + symlink dict, rooted anywhere."""

    def __init__(self, files=None, links=None):
        self.files = dict(files or {})
        self.links = dict(links or {})

    def read(self, path):
        if path in self.files:
            return self.files[path]
        raise HostError(f"read {path}: No such file")

    def exists(self, path):
        return path in self.files or path in self.links

    def listdir(self, path):
        prefix = path.rstrip("/") + "/"
        names = {
            k[len(prefix):].split("/")[0]
            for k in list(self.files) + list(self.links)
            if k.startswith(prefix)
        }
        return sorted(names)

    def resolve_realpath(self, path):
        if path in self.links:
            return os.path.normpath(
                os.path.join(os.path.dirname(path), self.links[path])
            )
        return path


# ---------------------------------------------------------------- dmesg parse


def test_parses_canonical_rtl8188eu_failure():
    line = (
        "[   12.345678] usb 1-2: rtl8xxxu: Direct firmware load for "
        "rtlwifi/rtl8188eufw.bin failed with error -2"
    )
    failures = parse_dmesg_firmware_failures([line])
    assert len(failures) == 1
    f = failures[0]
    assert isinstance(f, FirmwareFailure)
    assert f.firmware_path == "rtlwifi/rtl8188eufw.bin"
    assert f.error == -2  # ENOENT (linux-kernel.md §6)
    assert f.valid is True
    assert f.line_index == 0


def test_parser_ignores_noise_and_keeps_input_order():
    lines = [
        "usbcore: registered new interface driver mt7601u",
        "[  9.1] mt7601u 1-2:1.0: Direct firmware load for mt7601u.bin failed with error -2",
        "random kernel noise without the pattern",
        "[ 11.0] ath9k_htc 1-3:1.0: Direct firmware load for "
        "ath9k_htc/htc_9271-1.4.0.fw failed with error -12",
    ]
    failures = parse_dmesg_firmware_failures(lines)
    assert [(f.firmware_path, f.error, f.line_index) for f in failures] == [
        ("mt7601u.bin", -2, 1),
        ("ath9k_htc/htc_9271-1.4.0.fw", -12, 3),
    ]


@pytest.mark.parametrize(
    "bad_name",
    [
        "../../etc/shadow",  # path traversal
        "/etc/passwd",  # absolute
        "rtlwifi/%s.bin",  # format-string hostile
        "rtlwifi/*.bin",  # glob hostile
    ],
)
def test_hostile_filenames_flagged_invalid_not_crashing(bad_name):
    line = f"[ 1.0] usb 1-2: Direct firmware load for {bad_name} failed with error -2"
    failures = parse_dmesg_firmware_failures([line])
    assert len(failures) == 1
    assert failures[0].valid is False
    assert failures[0].firmware_path == bad_name
    assert failures[0].detail  # explainable reason, never silent


def test_no_failures_yields_empty_tuple():
    assert parse_dmesg_firmware_failures(["nothing here"]) == ()
    assert parse_dmesg_firmware_failures([]) == ()


# ------------------------------------------------------------- presence check


def test_present_raw_file_reports_installed(tmp_path):
    host = FakeHost({"/lib/firmware/mt7601u.bin": "\x00binary"})
    st = check_firmware_presence(host, module="mt7601u", rel_path="mt7601u.bin")
    assert isinstance(st, FirmwareStatus)
    assert st.installed is True
    assert st.found_form == "raw"
    assert any("mt7601u.bin" in e.detail for e in st.evidence)


def test_compressed_zst_suffix_tolerated():
    host = FakeHost({"/lib/firmware/mediatek/mt7610u.bin.zst": "\x00zst"})
    st = check_firmware_presence(
        host, module="mt76x0u", rel_path="mediatek/mt7610u.bin"
    )
    assert st.installed is True
    assert st.found_form == ".zst"


def test_absent_file_reports_not_installed_with_evidence():
    host = FakeHost({})
    st = check_firmware_presence(
        host, module="rtl8xxxu", rel_path="rtlwifi/rtl8188eufw.bin"
    )
    assert st.installed is False
    assert st.found_form is None
    assert st.normalized_path == "rtlwifi/rtl8188eufw.bin"
    assert st.evidence  # absence is also recorded, not silent


def test_traversal_request_is_rejected_by_grammar_never_queried():
    host = FakeHost()
    st = check_firmware_presence(host, module="x", rel_path="../evil.bin")
    assert st.installed is None  # indeterminate, not a fake False
    assert st.normalized_path is None
    assert all("/lib/firmware/../evil.bin" != e.detail for e in st.evidence)


# ------------------------------------------------------------- KB -> package


@pytest.fixture(scope="module")
def kb():
    from dongle_rescue.firmware.resolver import load_chipset_kb

    return load_chipset_kb()


def test_mt7601_maps_to_firmware_mediatek(kb):
    m = map_firmware_to_packages(kb, "mt7601u.bin")
    assert m.chipset == "MT7601U"
    assert m.packages == ("firmware-mediatek", "linux-firmware")
    assert m.confidence == Confidence.CONFIRMED
    assert m.evidence


def test_whence_link_alias_resolved_by_basename(kb):
    # WHENCE declares File: mediatek/mt7601u.bin + Link: mt7601u.bin ->
    # (firmware-supply-chain.md §1.5); requesting either spelling must match.
    m = map_firmware_to_packages(kb, "mediatek/mt7601u.bin")
    assert m.packages == ("firmware-mediatek", "linux-firmware")


def test_rtl8188eu_maps_to_firmware_realtek(kb):
    m = map_firmware_to_packages(kb, "rtlwifi/rtl8188eufw.bin")
    assert m.packages == ("firmware-realtek", "linux-firmware")
    assert m.confidence == Confidence.HIGH_CONFIDENCE


def test_unknown_file_is_honest_unknown(kb):
    m = map_firmware_to_packages(kb, "some/unknown.bin")
    assert m.packages == ()
    assert m.confidence == Confidence.UNKNOWN
    assert m.chipset is None


# ------------------------------------------------------- pkg manager detection


def _which_factory(found):
    def which(name):
        return found.get(name)

    return which


def test_detect_apt_only():
    assert detect_package_managers(_which_factory({"apt": "/usr/bin/apt"})) == (
        "apt",
    )


def test_detect_order_is_fixed_regardless_of_environment():
    found = {"pacman": "/usr/bin/pacman", "dnf": "/usr/bin/dnf", "apt": "/usr/bin/apt"}
    assert detect_package_managers(_which_factory(found)) == ("apt", "dnf", "pacman")


def test_detect_none_means_empty_not_guess():
    assert detect_package_managers(_which_factory({})) == ()


# ------------------------------------------------------------ install command


def test_apt_install_command_matches_task_example():
    cmd = build_install_command("apt", ["firmware-mediatek"])
    assert cmd == "apt-get install firmware-mediatek"


def test_dnf_and_pacman_variants():
    assert build_install_command("dnf", ["linux-firmware"]) == (
        "dnf install linux-firmware"
    )
    assert build_install_command("pacman", ["linux-firmware"]) == (
        "pacman -S linux-firmware"
    )


@pytest.mark.parametrize("bad", ["firmware;x", "a b", "$(evil)", "", "../pkg"])
def test_hostile_package_names_rejected_before_string_building(bad):
    with pytest.raises(ValueError):
        build_install_command("apt", [bad])


def test_unknown_manager_rejected():
    with pytest.raises(ValueError):
        build_install_command("yum", ["firmware-realtek"])


# ---------------------------------------------------------- RecommendedAction


def test_missing_fw_with_mapping_produces_display_only_install_action(kb):
    host = FakeHost({})
    st = check_firmware_presence(host, "mt7601u", "mt7601u.bin")
    st = FirmwareStatus(
        **{**st.__dict__, "mapping": map_firmware_to_packages(kb, "mt7601u.bin")}
    )
    action = recommend_firmware_action(st, managers=("apt",))
    assert isinstance(action, RecommendedAction)
    assert action.kind == "install_firmware_package"
    assert action.commands == ("apt-get install firmware-mediatek",)
    # SPEC §37 / ADR 0002 S4-S5: never automated, never silent network/root work.
    assert action.network_required is True
    assert action.requires_root is True
    assert action.safe_for_automation is False
    assert action.explanation
    assert action.evidence  # cited chain dmesg/module -> file -> package


def test_installed_fw_means_no_action():
    host = FakeHost({"/lib/firmware/mt7601u.bin": "x"})
    st = check_firmware_presence(host, "mt7601u", "mt7601u.bin")
    action = recommend_firmware_action(st, managers=("apt",))
    assert action.kind == "no_action"
    assert action.commands == ()


def test_no_manager_detected_is_explained_without_commands(kb):
    host = FakeHost({})
    st = check_firmware_presence(host, "mt7601u", "mt7601u.bin")
    st = FirmwareStatus(
        **{**st.__dict__, "mapping": map_firmware_to_packages(kb, "mt7601u.bin")}
    )
    action = recommend_firmware_action(st, managers=())
    assert action.kind == "install_firmware_package"
    assert action.commands == ()  # nothing to run: no channel detected
    assert "no package manager" in action.explanation.lower()


def test_unknown_package_owner_points_to_lookup_not_invention(kb):
    host = FakeHost({})
    st = check_firmware_presence(host, "mymod", "unknown/blob.bin")
    st = FirmwareStatus(
        **{**st.__dict__, "mapping": map_firmware_to_packages(kb, "unknown/blob.bin")}
    )
    action = recommend_firmware_action(st, managers=("apt",))
    assert action.kind == "manual_package_lookup"
    assert action.safe_for_automation is False
    assert "unknown" in action.explanation.lower()


# ------------------------------------------------------------- orchestrator


def test_resolve_module_firmware_end_to_end_offline():
    from dongle_rescue.firmware.resolver import resolve_module_firmware

    host = FakeHost({"/lib/firmware/mt7601u.bin": "\x00"})
    dmesg = [
        "[ 9.1] mt7601u 1-2:1.0: Direct firmware load for mt7601u.bin failed with error -2",
    ]
    statuses = resolve_module_firmware(
        host,
        module="mt7601u",
        firmware_paths=["mt7601u.bin"],
        dmesg_lines=dmesg,
        which=_which_factory({"apt": "/usr/bin/apt"}),
    )
    assert len(statuses) == 1
    st = statuses[0]
    assert st.installed is True
    assert st.mapping is not None
    assert st.mapping.packages == ("firmware-mediatek", "linux-firmware")
    assert st.failures[0].error == -2
    action = recommend_firmware_action(st, managers=("apt",))
    # Present on disk despite an old dmesg scar -> no install proposed.
    assert action.kind == "no_action"


def test_kb_loader_reads_versioned_data():
    from dongle_rescue.firmware.resolver import load_chipset_kb

    kb = load_chipset_kb()
    assert kb["schema_version"] == 1
    names = [c["chipset"] for c in kb["chipsets"]]
    assert "MT7601U" in names and "RTL8811CU" in names
