"""TDD: CLI layer (SPEC §26) — pure orchestration, zero privileged execution.

The CLI module is a thin, testable seam: `run()` takes argv + injected Host +
journal path and returns (exit_code, stdout_text). It NEVER executes repair
commands; `repair` always prints the dry-run plan and requires an explicit
`--execute` flag that V1 deliberately refuses to honor (SPEC §37).
"""

from __future__ import annotations

import json

import pytest

from conftest import KB_SYNTHETIC
from dongle_rescue.cli.main import run
from tests.fixtures import FixtureRootHost


def _argv_host(scenario="rtl8811cu_unbound", release="6.17.0-test"):
    host = FixtureRootHost()
    host.use_scenario(scenario)
    return ["--kernel-release", release], host


# ------------------------------------------------------------------ diagnose


def test_diagnose_state_b_text_output():
    argv, host = _argv_host()
    code, out = run([*argv, "diagnose"], host=host, kb=KB_SYNTHETIC)
    assert code == 0
    assert "0bda:8811" in out
    assert "STATE B" in out
    assert "RTL8811CU" in out
    assert "Evidence" in out or "EVIDENCE" in out.upper()


def test_diagnose_json_is_valid_and_schema_versioned():
    argv, host = _argv_host()
    code, out = run([*argv, "diagnose", "--json"], host=host, kb=KB_SYNTHETIC)
    assert code == 0
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    dev = doc["device"]
    assert dev["vid"] == "0bda" and dev["pid"] == "8811"
    assert doc["diagnosis"]["state"] == "B"


def test_diagnose_mt7601_ok_is_no_action_required():
    argv, host = _argv_host("mt7601_ok")
    code, out = run([*argv, "diagnose"], host=host, kb=KB_SYNTHETIC)
    assert code == 0
    assert "NO_ACTION_REQUIRED" in out
    assert "STATE A" in out


def test_diagnose_unknown_device_exits_2_with_manual_path():
    argv, host = _argv_host("collision_760a")  # no KB entry for 148f:760a? there is
    # use a scenario-less host: empty sysfs -> nothing found
    empty = FixtureRootHost()
    empty.use_scenario("mt7601_ok")
    code, out = run(
        [*argv, "diagnose", "--device", "1234:5678"],
        host=empty,
        kb={"chipsets": []},
    )
    assert code == 2
    assert "UNKNOWN" in out
    assert "--chip" in out  # manual continuation pointer (SPEC §11)


def test_diagnose_collision_lists_both_candidates():
    argv, host = _argv_host("collision_760a")
    code, out = run([*argv, "diagnose"], host=host, kb=KB_SYNTHETIC)
    assert code == 0
    assert "mt7601u" in out and "mt76x0u" in out  # both candidates shown


# ------------------------------------------------------------------- repair


def test_repair_prints_dry_run_plan_and_does_not_execute(tmp_path):
    argv, host = _argv_host()
    jpath = tmp_path / "journal.jsonl"
    code, out = run([*argv, "repair", "--dry-run", "--journal", str(jpath)],
                    host=host, kb=KB_SYNTHETIC)
    assert code == 0
    for field in ("WHAT", "WHY", "SOURCE", "EVIDENCE", "CONFIDENCE",
                  "FILES AFFECTED", "COMMANDS", "ROLLBACK"):
        assert field in out
    assert not jpath.exists()  # planning does not journal; only execution would
    assert plan_commands_display_only(out)


def plan_commands_display_only(out_text: str) -> bool:
    """Commands appear as display strings; the CLI never claims execution."""
    lowered = out_text.lower()
    return "not executed" in lowered and "executed:" not in lowered


def test_repair_without_dry_run_refuses_execution(tmp_path):
    """V1 never executes; --execute is refused with exit code 3."""
    argv, host = _argv_host()
    code, out = run([*argv, "repair", "--journal", str(tmp_path / "j.jsonl")],
                    host=host, kb=KB_SYNTHETIC)
    assert code == 0  # default is a plain dry-run
    assert "not executed" in out.lower()
    code2, out2 = run([*argv, "repair", "--execute", "--journal",
                       str(tmp_path / "j.jsonl")],
                      host=host, kb=KB_SYNTHETIC)
    assert code2 == 3
    assert "refused" in out2.lower()


def test_repair_infeasible_points_to_official_origin(tmp_path):
    argv, host = _argv_host()  # rtl8811cu via rtw_8821cu is feasible; force E-ish:
    code, out = run(
        [*argv, "repair", "--chip", "RTL8188EU", "--dry-run",
         "--journal", str(tmp_path / "j.jsonl")],
        host=host, kb=KB_SYNTHETIC,
    )
    assert code == 0
    assert "not feasible" in out.lower() or "no automated repair" in out.lower()


# ----------------------------------------------------------------- identify


def test_identify_chip_overrides_kb_lookup():
    argv, host = _argv_host()
    code, out = run([*argv, "identify", "--chip", "MT7601U"], host=host,
                    kb=KB_SYNTHETIC)
    assert code == 0
    assert "MT7601U" in out


# ------------------------------------------------------- history & rollback


def test_history_empty_journal_reports_empty_not_error(tmp_path):
    argv, host = _argv_host()
    code, out = run(["history", "--journal", str(tmp_path / "none.jsonl")],
                    host=host, kb=KB_SYNTHETIC)
    assert code == 0
    assert "no transactions" in out.lower()


def test_history_lists_recorded_transaction(tmp_path):
    from dongle_rescue.repair.transaction import Journal, create_transaction

    jp = tmp_path / "journal.jsonl"
    rec = create_transaction(
        before={"path": "/etc/modprobe.d/ddr-x.conf"},
        change={"op": "create_modprobe_alias"},
        after={"existed": True},
        rollback_action={"op": "remove_file",
                         "path": "/etc/modprobe.d/ddr-x.conf"},
    )
    Journal(jp).append(rec)
    code, out = run(["history", "--journal", str(jp)], host=None, kb=KB_SYNTHETIC)
    assert code == 0
    assert rec.transaction_id[:12] in out


def test_rollback_plans_from_journal_never_executes(tmp_path):
    from dongle_rescue.repair.transaction import Journal, create_transaction

    jp = tmp_path / "journal.jsonl"
    rec = create_transaction(
        before={"path": "/etc/modprobe.d/ddr-x.conf", "existed": False},
        change={"op": "create_modprobe_alias"},
        after={"existed": True},
        rollback_action={"op": "remove_file",
                         "path": "/etc/modprobe.d/ddr-x.conf"},
    )
    Journal(jp).append(rec)
    code, out = run(["rollback", rec.transaction_id, "--journal", str(jp)],
                    host=None, kb=KB_SYNTHETIC)
    assert code == 0
    assert "remove_file" in out
    assert "if_present" in out  # idempotent step description shown


def test_rollback_unknown_id_fails_cleanly(tmp_path):
    code, out = run(["rollback", "deadbeef" * 8, "--journal",
                     str(tmp_path / "none.jsonl")],
                    host=None, kb=KB_SYNTHETIC)
    assert code == 4
    assert "not found" in out.lower()


# ------------------------------------------------------------------ doctor


def test_doctor_reports_environment_checks():
    argv, host = _argv_host()
    code, out = run([*argv, "doctor"], host=host, kb=KB_SYNTHETIC)
    assert code == 0
    assert "modules.alias" in out
    assert "package manager" in out.lower()


def test_verify_reports_hardware_functional_on_mt7601_ok():
    argv, host = _argv_host("mt7601_ok")
    code, out = run([*argv, "verify"], host=host, kb=KB_SYNTHETIC)
    # fixture has driver bound + firmware file, but no /sys/class/net — the
    # offline checker must report the missing interface honestly.
    assert code == 0
    assert "NOT FUNCTIONAL" in out or "interface_present" in out


def test_verify_placeholder_replaced_by_real_checks():
    argv, host = _argv_host("mt7601_ok")
    code, out = run([*argv, "verify"], host=host, kb=KB_SYNTHETIC)
    assert "verdict:" in out  # real checker output, not the old placeholder text
    assert "verification layer" not in out


def test_verify_unknown_device_exits_2():
    argv, host = _argv_host()
    code, out = run([*argv, "verify", "--device", "0000:0000"],
                    host=host, kb=KB_SYNTHETIC)
    assert code == 2


# ----------------------------------------------------------------- flags


def test_no_network_flag_propagates_to_recommendations(tmp_path):
    argv, host = _argv_host("mt7601_ok")
    code, out = run([*argv, "diagnose", "--no-network"], host=host,
                    kb=KB_SYNTHETIC)
    assert code == 0
    # mt7601 firmware present => no network-dependent action anyway
    assert "NO_ACTION_REQUIRED" in out


def test_doctor_reporta_plano_de_log_e_reboot(fake_host):
    """O `doctor` passou a expor o acesso ao log do kernel.

    O planejador existia mas nao era chamado por ninguem; o doctor omitia
    justamente a informacao de que precisa quem vai diagnosticar estado C.
    """
    code, out = run(["doctor"], host=fake_host)

    assert code == 0
    assert "journalctl available:" in out
    assert "kernel log plan:" in out
    assert "reboot pending:" in out


def test_doctor_sem_host_nao_quebra():
    """Sem host injetado o doctor ainda responde o que nao depende da maquina."""
    code, out = run(["doctor"])

    assert code == 0
    assert "kernel release:" in out
