"""TDD: identification resolver — SPEC §7 chain over alias + KB."""

from __future__ import annotations

from conftest import ALIAS_MT7601_BOUND_SCENARIO, KB_SYNTHETIC, make_device
from dongle_rescue.identification.resolver import resolve_device
from dongle_rescue.types import Confidence


def test_mt7601_canonical_id_resolves_chipset_and_candidate():
    dev = make_device(vid="148f", pid="7601")
    res = resolve_device(dev, ALIAS_MT7601_BOUND_SCENARIO, KB_SYNTHETIC)
    assert res.chipset_id.chipset == "MT7601U"
    assert res.chipset_id.confidence == Confidence.CONFIRMED
    mods = [c.module for c in res.candidates]
    assert mods == ["mt7601u"]
    assert res.candidates[0].source == "modules.alias"
    assert any("v148Fp7601" in e.detail for e in res.candidates[0].evidence)


def test_collision_yields_both_candidates_in_file_order():
    dev = make_device(vid="148f", pid="760a")
    res = resolve_device(dev, ALIAS_MT7601_BOUND_SCENARIO, KB_SYNTHETIC)
    assert [c.module for c in res.candidates] == ["mt7601u", "mt76x0u"]


def test_kb_known_id_missing_from_alias_still_yields_kb_candidates():
    # RTL8811CU 0bda:8811: not in the synthetic alias file, but KB knows it.
    dev = make_device(vid="0bda", pid="8811")
    res = resolve_device(dev, ALIAS_MT7601_BOUND_SCENARIO, KB_SYNTHETIC)
    assert res.chipset_id.chipset == "RTL8811CU"
    assert [c.module for c in res.candidates] == ["rtw_8821cu"]
    assert res.candidates[0].source == "chipsets.json"


def test_completely_unknown_device_is_honest_unknown():
    dev = make_device(vid="1234", pid="5678")
    res = resolve_device(dev, ALIAS_MT7601_BOUND_SCENARIO, KB_SYNTHETIC)
    assert res.chipset_id.chipset == "UNKNOWN"
    assert res.chipset_id.confidence == Confidence.UNKNOWN
    assert res.candidates == ()
    assert res.missing_link  # explainable: which link failed


def test_hostile_product_string_never_breaks_evidence():
    dev = make_device(vid="148f", pid="7601", product="NIC\n%s*pwn\x1b[31m")
    res = resolve_device(dev, ALIAS_MT7601_BOUND_SCENARIO, KB_SYNTHETIC)
    for e in res.chipset_id.evidence:
        assert "\n" not in e.detail and "\x1b" not in e.detail
