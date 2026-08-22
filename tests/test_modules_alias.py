"""TDD: modules.alias parser + deterministic glob matcher (SPEC §7 layer 3).

The matcher is pure: lines in, module names out, in file order. Hostile
patterns never crash it (ADR 0002 S6: untrusted input).
"""

from __future__ import annotations

import pytest

from dongle_rescue.host import HostError
from conftest import FakeHost
from dongle_rescue.linux.modules_alias import (
    AliasLine,
    match,
    match_with_lines,
    modules_alias_path,
    parse_alias_lines,
    read_alias_lines,
)


LINES = [
    "# comment",
    "",
    "alias usb:v148Fp7601d*dc*dsc*dp*ic*isc*ip*in* mt7601u",
    "alias usb:v148Fp760Ad*dc*dsc*dp*ic*isc*ip*in* mt7601u",
    "alias usb:v148Fp760Ad*dc*dsc*dp*ic*isc*ip*in* mt76x0u",
    "alias pci:v000010ECd00008168sv*sd*bc02sc06i* r8169",
    "alias platform:e1000e e1000e",
]


def test_parse_keeps_only_usb_alias_rows_in_file_order():
    parsed = parse_alias_lines(LINES)
    assert [a.module for a in parsed] == ["mt7601u", "mt7601u", "mt76x0u"]
    assert all(a.pattern.startswith("usb:") for a in parsed)
    assert parsed[0].raw == LINES[2]  # original line preserved for evidence


def test_parse_tolerates_whitespace_and_crlf():
    parsed = parse_alias_lines(["alias usb:v148Fp7601d*\r\n  mt7601u\r\n"])
    # malformed (module on next line) is not an alias row -> skipped
    assert parsed == []


def test_match_returns_every_claiming_module_in_file_order():
    got = match("usb:v148Fp760Ad0200dc00dsc00dp00icFFisc00ip00in00", LINES)
    assert got == ["mt7601u", "mt76x0u"]  # collision: both, file order


def test_match_canonical_id_single_module():
    assert match("usb:v148Fp7601d0100dc00dsc00dp00icFFisc00ip00in00", LINES) == ["mt7601u"]


def test_match_device_level_modalias_without_interface_fields():
    assert match("usb:v148Fp7601d0100dc00dsc00dp00", LINES) == ["mt7601u"]


def test_match_no_hit_returns_empty_not_error():
    assert match("usb:v1234p5678d0000dc00dsc00dp00icFFiscFFipFFin00", LINES) == []


def test_match_is_pure_wildcard_only_star_semantics():
    # kernel globs use '*' only; '?'/'[' must be literal, not fnmatch metachars
    lines = [
        "alias usb:vAAAApBBBBd?dc*dsc*dp*ic*isc*ip*in* wrong",
        "alias usb:vAAAApBBBBd*dc*dsc*dp*ic*isc*ip*in* right",
    ]
    assert match("usb:vAAAApBBBBd0100dc00dsc00dp00icFFisc00ip00in00", lines) == ["right"]


def test_match_hostile_pattern_does_not_crash_or_overmatch():
    lines = [
        "alias usb:v[A-Z]*p* mt7601u",  # bracket glob from hostile alias file
        "alias usb:* mt76x0u",
    ]
    got = match("usb:v148Fp7601d0100dc00dsc00dp00", lines)
    assert got == ["mt76x0u"]  # bracket treated literally -> only catch-all hits


def test_match_hostile_modalias_input_is_sanitized_not_fatal():
    evil = "usb:v148Fp7601d0100dc00dsc00dp00icFFisc00ip00in" + "*" * 500
    assert match(evil, LINES) == []  # grammar violation -> no match, no raise
    assert match("", LINES) == []
    assert match("pci:v000010ECd00008168sv*sd*bc02sc06i*", LINES) == []  # non-usb


def test_match_with_lines_pairs_module_with_exact_source_line():
    got = match_with_lines(
        "usb:v148Fp760Ad0200dc00dsc00dp00icFFisc00ip00in00", LINES
    )
    assert got[0] == AliasLine(
        pattern="usb:v148Fp760Ad*dc*dsc*dp*ic*isc*ip*in*",
        module="mt7601u",
        raw=LINES[3],
    )
    assert got[1].raw == LINES[4]


def test_read_alias_lines_via_host(tmp_path):
    host = FakeHost({"/lib/modules/6.17.0-test/modules.alias": "\n".join(LINES)})
    got = read_alias_lines(host, release="6.17.0-test")
    assert len(got) == len(LINES)


def test_read_alias_lines_missing_release_raises_hosterror():
    with pytest.raises(HostError):
        read_alias_lines(FakeHost({}), release="9.9.9-missing")


def test_modules_alias_path_layout():
    assert modules_alias_path(release="6.17.0-1018-oracle") == (
        "/lib/modules/6.17.0-1018-oracle/modules.alias"
    )
